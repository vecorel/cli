"""Parquet writers for the GeoParquet specification.

This package contains version-specific writers and a dispatcher.

* GeoParquet 1.0.0 and 1.1.0 are written through :mod:`.geopandas`, which uses
  the geopandas Arrow path (WKB-encoded geometry + ``geo`` metadata).
* GeoParquet 2.0.0+ is written through :mod:`.duckdb`, which uses the DuckDB
  spatial extension to emit native Parquet ``GEOMETRY`` logical types. DuckDB
  is an optional dependency (install the ``parquet2`` pixi feature).
"""

from __future__ import annotations

from typing import Any, Optional


def _major_version(schema_version: Optional[str]) -> int:
    """Return the major part of a ``MAJOR.MINOR.PATCH`` version, or 0."""
    if not schema_version:
        return 0
    head = schema_version.split(".", 1)[0]
    try:
        return int(head)
    except ValueError:
        return 0


def to_parquet(
    df,
    path,
    *,
    schema_version: Optional[str] = None,
    **kwargs: Any,
):
    """Write a (Geo)DataFrame to GeoParquet, dispatching to the right backend.

    For ``schema_version`` < ``2.0.0`` (or unspecified) the geopandas writer
    is used. For ``2.0.0+`` the DuckDB writer is used (requires the optional
    ``duckdb`` dependency — install the ``parquet2`` pixi feature).
    """
    if _major_version(schema_version) >= 2:
        try:
            from .duckdb import to_parquet as _backend
        except ImportError as exc:  # pragma: no cover - depends on env
            raise ImportError(
                f"Writing GeoParquet {schema_version!r} requires the optional "
                "'duckdb' dependency. Install the 'parquet2' pixi feature, "
                "e.g. `pixi install -e parquet2`."
            ) from exc
    else:
        from .geopandas import to_parquet as _backend
    return _backend(df, path, schema_version=schema_version, **kwargs)


__all__ = ["to_parquet"]
