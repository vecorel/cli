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

from ..const import HILBERT_DEFAULT_LEVEL

# Geographic world bounds, used as the fallback when a CRS exposes no
# `area_of_use` (e.g. some custom or aggregated CRSs).
_GEOGRAPHIC_WORLD_BOUNDS = (-180.0, -90.0, 180.0, 90.0)


def crs_total_bounds(crs) -> tuple[float, float, float, float]:
    """Return a stable, deterministic ``(xmin, ymin, xmax, ymax)`` covering the
    CRS's valid extent expressed in the CRS's own coordinate units.

    For geographic CRSs this returns the CRS's declared ``area_of_use`` in
    degrees. For projected CRSs the geographic ``area_of_use`` is projected
    onto the CRS axes (sampled along a 25x25 grid to capture curvature).

    The result is independent of any particular dataset: it depends only on
    the CRS. Two independently-converted parts of the same dataset therefore
    share the same Hilbert reference grid and their orderings can be merged
    without recomputation.
    """
    from pyproj import CRS, Transformer

    if crs is None:
        return _GEOGRAPHIC_WORLD_BOUNDS

    c = CRS.from_user_input(crs)
    aou = c.area_of_use

    if c.is_geographic:
        if aou is None:
            return _GEOGRAPHIC_WORLD_BOUNDS
        return (float(aou.west), float(aou.south), float(aou.east), float(aou.north))

    if aou is None:
        raise ValueError(
            f"Cannot derive total bounds for projected CRS {crs!r}: no area_of_use defined"
        )

    transformer = Transformer.from_crs("EPSG:4326", c, always_xy=True)
    n = 25
    xs = np.linspace(aou.west, aou.east, n)
    ys = np.linspace(aou.south, aou.north, n)
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
    """
    from geopandas.tools.hilbert_curve import _continuous_to_discrete_coords, _encode

    x, y = _continuous_to_discrete_coords(bounds, level, list(total_bounds))
    return _encode(level, x, y).astype(np.uint64, copy=False)


def hilbert_sort_geodataframe(gdf, level: int = HILBERT_DEFAULT_LEVEL):
    """Return a copy of ``gdf`` sorted by Hilbert distance against the CRS's
    total bounds. The original index is reset.

    If ``gdf.crs`` is None or has no area_of_use, falls back to geographic
    world bounds; in that case the resulting order is still stable but Hilbert
    keys may not be comparable to other independently-produced outputs.
    """
    if gdf.empty:
        return gdf.reset_index(drop=True)

    total = crs_total_bounds(gdf.crs)
    bounds_2d: np.ndarray = gdf.geometry.bounds.to_numpy(dtype=np.float64, copy=False)
    keys = hilbert_distances_from_bounds(bounds_2d, total, level=level)
    order = np.argsort(keys, kind="stable")
    return gdf.iloc[order].reset_index(drop=True)


__all__ = [
    "crs_total_bounds",
    "hilbert_distances_from_bounds",
    "hilbert_sort_geodataframe",
]
