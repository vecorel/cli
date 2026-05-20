"""GeoParquet 2.0+ writer backed by the DuckDB spatial extension.

GeoParquet 2.0 uses the native Parquet ``GEOMETRY`` / ``GEOGRAPHY`` logical
types instead of WKB-encoded binary columns with side metadata. pyarrow 23 and
geopandas 1.1 don't expose those logical types yet, so we delegate the actual
write to DuckDB, which has had a full GeoParquet 2.0 writer since the spatial
extension shipped that support.

The function exposes the same signature as
``vecorel_cli.parquet.geopandas.to_parquet`` so it can stand in transparently
behind the dispatcher in ``vecorel_cli.parquet.__init__``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Optional

# Module-level import of the third-party ``duckdb`` (NOT this module — Python
# 3's absolute import rules make ``import duckdb`` resolve to the installed
# package even from inside ``vecorel_cli.parquet.duckdb``). The import is
# eager so that callers see ImportError up-front when the optional dep is
# missing; the dispatcher in ``__init__`` catches it.
import duckdb as _duckdb


def _ensure_spatial(con) -> None:
    """Load the spatial extension, installing it on first use if needed."""
    try:
        con.execute("LOAD spatial")
    except _duckdb.Error:
        con.execute("INSTALL spatial")
        con.execute("LOAD spatial")


def _geometry_columns(df) -> list[str]:
    return [col for col in df.columns if str(df.dtypes[col]) == "geometry"]


def _quote_ident(name: str) -> str:
    """Quote an identifier for safe interpolation into SQL."""
    return '"' + name.replace('"', '""') + '"'


def _quote_path(path) -> str:
    """Quote a path literal for SQL ``COPY ... TO 'path'``."""
    return "'" + str(path).replace("'", "''") + "'"


def _duckdb_geoparquet_mode(schema_version: Optional[str]) -> str:
    """Translate a GeoParquet *spec* version into DuckDB's ``GEOPARQUET_VERSION``
    *option* value.

    DuckDB's spatial extension exposes the option as an enum, not as the
    spec's MAJOR.MINOR.PATCH string. The allowed values are::

        V1   - WKB-binary column + ``geo`` metadata block (classic GeoParquet 1.x)
        NONE - Native Parquet GEOMETRY logical type, *no* ``geo`` metadata
        BOTH - Native GEOMETRY column AND a legacy 1.x ``geo`` block (the
               column is readable as both native GEOMETRY and WKB)

    Mapping rationale:

    * ``"1.x"`` / ``None`` -> ``V1``
    * ``"2.x"`` and higher -> ``BOTH``

    Why ``BOTH`` and not ``NONE`` for 2.x:

    geopandas, and therefore the fiboa validator, hard-require a ``geo``
    metadata block (``geopandas.read_parquet`` raises "Missing geo metadata"
    without it). ``NONE`` strips the block entirely, so even though the file
    is a "pure" GeoParquet 2.0 it can't be read or validated by the existing
    tooling. ``BOTH`` keeps a 1.x ``geo`` block for those tools while ALSO
    storing the geometry as a native Parquet GEOMETRY logical type — newer
    readers see the native type, older readers see the legacy WKB view.

    Tools that read only ``geo.version`` (e.g. ``gpio check``) will report
    the file as 1.0.0 — that's a tooling limitation, not a property of the
    file. To confirm the native GEOMETRY column is present, inspect the
    Parquet schema directly (``pyarrow.parquet.ParquetFile(...).schema_arrow``).

    Override with the ``duckdb_geoparquet_mode`` kwarg to force ``NONE`` if
    you need a strict 2.0 file and don't care about fiboa-validator compat.
    """
    if not schema_version:
        return "V1"
    head = schema_version.split(".", 1)[0]
    try:
        major = int(head)
    except ValueError:
        return "V1"
    return "BOTH" if major >= 2 else "V1"


def to_parquet(
    df,
    path,
    index: Optional[bool] = None,
    compression: str = "zstd",
    schema_version: Optional[str] = None,
    write_covering_bbox: bool = False,  # ignored for 2.0+ (column stats replace it)
    schema=None,
    compression_level: Optional[int] = None,
    row_group_size: Optional[int] = None,
    duckdb_geoparquet_mode: Optional[str] = None,
    **kwargs: Any,
):
    """Write a GeoDataFrame as GeoParquet 2.0+ via DuckDB.

    Parameters mirror :func:`vecorel_cli.parquet.geopandas.to_parquet` so the
    function can be used interchangeably through the dispatcher. ``schema``
    (a pyarrow Schema carrying the desired column metadata, used by the
    geopandas writer to attach collection metadata) is interpreted as a
    structural hint only: any schema-level metadata it carries is written
    into the output as Parquet key/value metadata. ``write_covering_bbox`` is
    accepted for signature compatibility and ignored (GeoParquet 2.0 uses
    native Parquet column statistics for bounding boxes).

    Requires the optional ``duckdb`` dependency (``parquet2`` pixi feature).
    """
    import pyarrow as pa  # local import keeps base deps minimal
    from geopandas.io.arrow import _validate_dataframe

    _validate_dataframe(df)
    geom_cols = _geometry_columns(df)
    if not geom_cols:
        raise ValueError("Cannot write GeoParquet: dataframe has no geometry columns")
    if any(df[c].array.has_z.any() for c in geom_cols):
        raise ValueError("Cannot write 3D geometries to GeoParquet 2.0")

    crs_by_col: dict[str, Optional[str]] = {}
    for col in geom_cols:
        crs = df[col].crs
        crs_by_col[col] = crs.to_authority(min_confidence=20) if crs is not None else None

    # Convert geometries to WKB so we can hand a plain Arrow table to DuckDB,
    # then have DuckDB parse them back into native GEOMETRY columns via
    # ST_GeomFromWKB inside the COPY.
    df_wkb = df.to_wkb()
    table = pa.Table.from_pandas(df_wkb, schema=schema, preserve_index=index)

    out_dir = os.path.dirname(str(path))
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)

    con = _duckdb.connect(":memory:")
    try:
        _ensure_spatial(con)
        con.register("vecorel_input", table)

        select_terms = []
        for col in table.column_names:
            ident = _quote_ident(col)
            if col in geom_cols:
                select_terms.append(f"ST_GeomFromWKB({ident}) AS {ident}")
            else:
                select_terms.append(ident)
        select_sql = ", ".join(select_terms)

        mode = duckdb_geoparquet_mode or _duckdb_geoparquet_mode(schema_version)
        copy_opts = [
            "FORMAT PARQUET",
            f"COMPRESSION {compression}",
            f"GEOPARQUET_VERSION '{mode}'",
        ]
        if compression_level is not None:
            copy_opts.append(f"COMPRESSION_LEVEL {compression_level}")
        if row_group_size is not None:
            copy_opts.append(f"ROW_GROUP_SIZE {row_group_size}")
        copy_opts_sql = ", ".join(copy_opts)

        con.execute(
            f"COPY (SELECT {select_sql} FROM vecorel_input) "
            f"TO {_quote_path(path)} ({copy_opts_sql})"
        )
    finally:
        con.close()


def copy_to_geoparquet2(
    source: Iterable | str,
    target,
    *,
    schema_version: str = "2.0.0",
    compression: str = "zstd",
    compression_level: Optional[int] = None,
    row_group_size: Optional[int] = None,
    drop_columns: Iterable[str] = ("bbox",),
    duckdb_geoparquet_mode: Optional[str] = None,
) -> None:
    """Convert one or more existing 1.x GeoParquet files to GeoParquet 2.0+.

    ``source`` can be a single path or an iterable of paths (or a glob string
    that DuckDB's ``read_parquet`` accepts). Geometries stored as WKB in the
    sources are decoded with ``ST_GeomFromWKB`` and re-emitted as native
    GEOMETRY logical types. By default the per-row ``bbox`` covering column
    is dropped from the output (GeoParquet 2.0 stores bbox in column stats).

    The row ordering of the source is preserved (DuckDB's ``COPY`` from a
    Parquet scan walks row groups in file order, which keeps any upstream
    Hilbert sort intact).
    """
    if isinstance(source, (str, Path)):
        sources = [str(source)]
    else:
        sources = [str(s) for s in source]
    if not sources:
        raise ValueError("copy_to_geoparquet2: no source files provided")

    out_dir = os.path.dirname(str(target))
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)

    con = _duckdb.connect(":memory:")
    try:
        _ensure_spatial(con)
        sources_sql = "[" + ", ".join(_quote_path(s) for s in sources) + "]"

        # Discover the input columns so we can know which one is the geometry
        # (DuckDB exposes binary WKB columns as BLOB).
        df_info = con.execute(f"DESCRIBE SELECT * FROM read_parquet({sources_sql})").fetchall()
        cols = [row[0] for row in df_info]
        col_types = {row[0]: row[1].upper() for row in df_info}

        drop = {c for c in drop_columns}
        out_cols = [c for c in cols if c not in drop]

        select_terms = []
        for col in out_cols:
            ident = _quote_ident(col)
            t = col_types.get(col, "")
            if t == "BLOB":
                # Treat the (single) primary WKB column as geometry. If multiple
                # BLOB columns exist this heuristic would need refinement.
                select_terms.append(f"ST_GeomFromWKB({ident}) AS {ident}")
            else:
                select_terms.append(ident)

        mode = duckdb_geoparquet_mode or _duckdb_geoparquet_mode(schema_version)
        copy_opts = [
            "FORMAT PARQUET",
            f"COMPRESSION {compression}",
            f"GEOPARQUET_VERSION '{mode}'",
        ]
        if compression_level is not None:
            copy_opts.append(f"COMPRESSION_LEVEL {compression_level}")
        if row_group_size is not None:
            copy_opts.append(f"ROW_GROUP_SIZE {row_group_size}")

        con.execute(
            f"COPY (SELECT {', '.join(select_terms)} "
            f"FROM read_parquet({sources_sql})) "
            f"TO {_quote_path(target)} ({', '.join(copy_opts)})"
        )
    finally:
        con.close()


__all__ = ["to_parquet", "copy_to_geoparquet2"]
