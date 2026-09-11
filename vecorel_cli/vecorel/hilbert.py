"""Hilbert curve sorting against CRS-stable reference bounds.

Sorting by Hilbert distance gives row groups good spatial locality, which
improves bbox-pushdown query performance and downstream compression. We
deliberately sort against the *CRS's* declared extent rather than the
dataframe's own bbox: that way, two independently produced files (for
example two provincial parts that will be merged later) end up using the
same Hilbert reference grid, and their orderings are comparable.
"""

from __future__ import annotations

import numpy as np
from loguru import logger

from ..const import HILBERT_DEFAULT_LEVEL

# Geographic world bounds, used as the fallback when a CRS exposes no
# `area_of_use` (e.g. some custom or aggregated CRSs).
_GEOGRAPHIC_WORLD_BOUNDS = (-180.0, -90.0, 180.0, 90.0)


def crs_total_bounds(crs) -> tuple[float, float, float, float]:
    """Return a stable, deterministic ``(xmin, ymin, xmax, ymax)`` covering the
    CRS's valid extent expressed in the CRS's own coordinate units.

    The CRS's ``area_of_use`` (which pyproj always reports as WGS84 degrees,
    regardless of the CRS's own units or prime meridian) is projected onto the
    CRS axes, sampled along a 25x25 grid to capture curvature. Antimeridian-
    spanning areas of use (``west > east``, e.g. New Zealand) are sampled
    across the wrapped longitude span.

    The result is independent of any particular dataset: it depends only on
    the CRS. Two independently-converted parts of the same dataset therefore
    share the same Hilbert reference grid and their orderings can be merged
    without recomputation.

    Raises ``ValueError`` for a projected CRS without a declared area of use;
    callers that can tolerate a dataset-dependent grid should catch it and
    substitute their own reference extent.
    """
    from pyproj import CRS, Transformer

    if crs is None:
        return _GEOGRAPHIC_WORLD_BOUNDS

    c = CRS.from_user_input(crs)
    aou = c.area_of_use

    if aou is None:
        if c.is_geographic:
            return _GEOGRAPHIC_WORLD_BOUNDS
        raise ValueError(
            f"Cannot derive total bounds for projected CRS {crs!r}: no area_of_use defined"
        )

    west, south, east, north = (
        float(aou.west),
        float(aou.south),
        float(aou.east),
        float(aou.north),
    )
    # Antimeridian-spanning area of use: sample across the wrapped span.
    # pyproj accepts longitudes beyond 180 and wraps them itself.
    if west > east:
        east += 360.0

    # Sample the (WGS84) area of use into the target CRS. This also applies to
    # geographic target CRSs: their own axes may use different units (grads)
    # or a non-Greenwich prime meridian, so the AoU degrees cannot be returned
    # verbatim.
    transformer = Transformer.from_crs("EPSG:4326", c, always_xy=True)
    n = 25
    xs = np.linspace(west, east, n)
    ys = np.linspace(south, north, n)
    grid_x, grid_y = np.meshgrid(xs, ys)
    px, py = transformer.transform(grid_x.ravel(), grid_y.ravel())
    px = np.asarray(px, dtype=np.float64)
    py = np.asarray(py, dtype=np.float64)
    mask = np.isfinite(px) & np.isfinite(py)
    if not mask.any():
        raise ValueError(f"Could not project area_of_use into CRS {crs!r}")
    return (
        float(px[mask].min()),
        float(py[mask].min()),
        float(px[mask].max()),
        float(py[mask].max()),
    )


def hilbert_distances_from_bounds(
    bounds: np.ndarray,
    total_bounds: tuple[float, float, float, float],
    level: int = HILBERT_DEFAULT_LEVEL,
) -> np.ndarray:
    """Compute per-row Hilbert distances from feature bbox rows + CRS bounds.

    ``bounds`` must be an ``(N, 4)`` float64 array of ``[xmin, ymin, xmax, ymax]``
    per feature. Returns a ``(N,)`` uint64 array of Hilbert keys; sorting by
    this key gives the Hilbert-curve ordering at the given resolution.

    This is the bbox-column twin of the public
    ``GeoSeries.hilbert_distance(total_bounds=..., level=...)`` (for callers
    that hold covering bboxes without decoded geometry, e.g. streaming
    parquet merges); a test asserts the two stay identical, guarding the
    private-API import below against geopandas changes.
    """
    from geopandas.tools.hilbert_curve import _continuous_to_discrete_coords, _encode

    x, y = _continuous_to_discrete_coords(bounds, level, list(total_bounds))
    return _encode(level, x, y).astype(np.uint64, copy=False)


def hilbert_reference_bounds(crs, fallback=None):
    """The CRS's own reference extent for the Hilbert grid, or ``fallback``.

    ``crs_total_bounds`` derives a dataset-independent grid from the CRS's area
    of use, so parts converted separately sort into the same order. A CRS given
    as a bare projection definition has no area of use to derive it from —
    Austria's 2018 edition ships an unnamed "MGI / Austria Lambert" that pyproj
    cannot match to an EPSG code — and there the data's own extent orders the
    file just as well; only mergeability with separately converted parts is
    lost. Returns None when neither is available, leaving the caller to decide
    whether that is fatal.
    """
    try:
        return crs_total_bounds(crs)
    except ValueError:
        return tuple(fallback) if fallback else None


def bounds_array_for_table(table, primary_col: str) -> np.ndarray:
    """Return an (N, 4) float64 array of [xmin, ymin, xmax, ymax] per feature.

    Uses the GeoParquet 1.1.0 covering ``bbox`` struct column when present
    (zero-decode); otherwise falls back to decoding WKB.
    """
    import pyarrow as pa

    if "bbox" in table.column_names and pa.types.is_struct(table.column("bbox").type):
        arr = table.column("bbox").combine_chunks()
        return np.column_stack(
            [
                arr.field("xmin").to_numpy(zero_copy_only=False),
                arr.field("ymin").to_numpy(zero_copy_only=False),
                arr.field("xmax").to_numpy(zero_copy_only=False),
                arr.field("ymax").to_numpy(zero_copy_only=False),
            ]
        ).astype(np.float64, copy=False)

    import shapely

    wkb_list = table.column(primary_col).combine_chunks().to_pylist()
    geoms = shapely.from_wkb(wkb_list)
    return shapely.bounds(geoms)


def hilbert_keys_for_table(table, primary_col: str, total_bounds) -> np.ndarray:
    bounds = bounds_array_for_table(table, primary_col)
    return hilbert_distances_from_bounds(bounds, total_bounds)


def ensure_hilbert_sorted(
    path: str,
    primary_col: str,
    total_bounds,
    compression: str,
    compression_level=None,
    row_group_size=None,
) -> bool:
    """If the GeoParquet file at ``path`` is already Hilbert-sorted against
    ``total_bounds``, leave it untouched and return False. Otherwise sort it
    in place and return True.

    The whole file is loaded into memory once for the sort. Schema metadata
    (``geo``, collection JSON, etc.) is preserved.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    # cheap check first: the keys only need the bbox covering column
    with pq.ParquetFile(path) as pf:
        has_bbox = "bbox" in pf.schema_arrow.names
        probe = pf.read(columns=["bbox"]) if has_bbox else pf.read()
    hilberts = hilbert_keys_for_table(probe, primary_col, total_bounds)
    # NB: hilberts is uint64; never use np.diff for monotonicity here — uint
    # underflow makes any descent wrap to a huge positive and fool the check.
    if hilberts.size <= 1 or bool(np.all(hilberts[1:] >= hilberts[:-1])):
        return False

    with pq.ParquetFile(path) as pf:
        table = pf.read()
        metadata = pf.schema_arrow.metadata
    narrow_schema = table.schema.with_metadata(metadata)

    # int32 offsets of plain binary/string columns overflow when a take()
    # concatenates >2 GB of chunks (large WKB columns); widen them for the
    # take, and cast each written batch back so the file keeps its original
    # schema (Parquet's physical BYTE_ARRAY is identical either way).
    fields = []
    widened = False
    for f in table.schema:
        if pa.types.is_binary(f.type):
            fields.append(f.with_type(pa.large_binary()))
            widened = True
        elif pa.types.is_string(f.type):
            fields.append(f.with_type(pa.large_string()))
            widened = True
        else:
            fields.append(f)
    if widened:
        table = table.cast(pa.schema(fields, metadata=table.schema.metadata))

    order = np.argsort(hilberts, kind="stable")
    sorted_table = table.take(pa.array(order))
    sorted_table = sorted_table.replace_schema_metadata(metadata)

    write_kwargs = {"compression": compression}
    if compression_level is not None:
        write_kwargs["compression_level"] = compression_level

    # Write batch-wise against the ORIGINAL narrow schema: each batch is far
    # below the int32 offset limit, so the down-cast is safe, the geo/collection
    # metadata is preserved, and the rewritten file schema-matches untouched
    # pre-sorted siblings during merges.
    step = row_group_size or 131_072
    writer = pq.ParquetWriter(path, narrow_schema, **write_kwargs)
    try:
        for start in range(0, sorted_table.num_rows, step):
            batch = sorted_table.slice(start, step)
            writer.write_table(batch.cast(narrow_schema) if widened else batch)
    finally:
        writer.close()
    return True


def hilbert_sort_geodataframe(gdf, level: int = HILBERT_DEFAULT_LEVEL):
    """Return a copy of ``gdf`` sorted by Hilbert distance against the CRS's
    total bounds. The original index is reset.

    If the CRS provides no stable extent (custom projected CRS without an
    area of use), the dataframe's own bounds are used instead: the order is
    still spatially local, but not comparable across independently-produced
    files.
    """
    if gdf.empty:
        return gdf.reset_index(drop=True)

    try:
        total = crs_total_bounds(gdf.crs)
    except ValueError as e:
        logger.warning(f"{e}; sorting against the dataset's own bounds instead")
        total = tuple(float(v) for v in gdf.total_bounds)

    # public geopandas API; level 16 = a 65,536 x 65,536 reference grid
    keys = gdf.geometry.hilbert_distance(total_bounds=list(total), level=level).to_numpy()
    order = np.argsort(keys, kind="stable")
    return gdf.iloc[order].reset_index(drop=True)


__all__ = [
    "bounds_array_for_table",
    "crs_total_bounds",
    "ensure_hilbert_sorted",
    "hilbert_distances_from_bounds",
    "hilbert_keys_for_table",
    "hilbert_reference_bounds",
    "hilbert_sort_geodataframe",
]
