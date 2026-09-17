import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from ..encoding.geojson import VecorelJSONEncoder
from ..encoding.geoparquet import GeoParquet
from ..vecorel.hilbert import hilbert_keys_for_table, hilbert_reference_bounds
from .base import BaseConverter


# COPY doesn't support bound parameters for read_parquet file names,
# so paths are inlined as escaped single-quoted string literals
def _sql_path(path) -> str:
    escaped = str(path).replace("'", "''")
    return f"'{escaped}'"


# A COPY statement binds its own parameters before those of its subquery, so a value
# placed in the SELECT cannot be a bound parameter: it would be read as the output path.
def _sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return repr(value)
    if isinstance(value, float):
        if np.isnan(value):
            return "'NaN'::DOUBLE"
        if np.isposinf(value):
            return "'Infinity'::DOUBLE"
        if np.isneginf(value):
            return "'-Infinity'::DOUBLE"
        return repr(value)
    if not isinstance(value, str):
        raise ValueError(f"Cannot use {value!r} as a constant column; it is not a scalar")
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _normalize_crs(crs):
    """The comparable pyproj CRS for a GeoParquet crs value,
    which defaults to OGC:CRS84 when missing."""
    from pyproj import CRS

    return CRS.from_user_input(crs if crs is not None else "OGC:CRS84")


def _equal_crs(a, b) -> bool:
    # GeoParquet coordinates are always x, y regardless of the CRS axis order
    return a.equals(b, ignore_axis_order=True)


# This converter is experimental, use with caution.
# Results may not be fully compliant yet.
# Use this primarily for datasets that are too large to be processed by the default converter.
class DuckDBBaseConverter(BaseConverter):
    def convert(
        self,
        output_file,
        cache=None,
        input_files=None,
        variant=None,
        compression=None,
        compression_level: Optional[int] = None,
        geoparquet_version=None,
        original_geometries=False,
        **kwargs,
    ) -> str:
        self.variant = variant
        cid = self.id.strip()
        if self.bbox is not None and len(self.bbox) != 4:
            raise ValueError("If provided, the bounding box must consist of 4 numbers")

        self._check_id_mapping()
        self._require_one_source_of_urls()
        self._prewarm_schemas()

        directory = os.path.dirname(output_file)
        if directory:
            os.makedirs(directory, exist_ok=True)

        if input_files is not None and isinstance(input_files, dict) and len(input_files) > 0:
            self.warning("Using user provided input file(s) instead of the pre-defined file(s)")
            urls = input_files
        else:
            urls = self.get_urls()
            if urls is None:
                raise ValueError("No input files provided")

        self.info("Getting file(s) if not cached yet")
        if cache:
            request_args = {}
            if self.avoid_range_request:
                request_args["block_size"] = 0
            urls = self.download_files(urls, cache, **request_args)
        elif self.avoid_range_request:
            self.warning(
                "avoid_range_request is set, but cache is not used, so this setting has no effect"
            )

        if isinstance(urls, str):
            sources = urls
        else:
            sources = [url[0] if isinstance(url, tuple) else url for url in urls]

        con = duckdb.connect()
        con.install_extension("spatial")
        con.load_extension("spatial")

        # Skip mapped columns that the source doesn't carry, like the
        # GeoDataFrame-based codepath does
        available = {
            row[0]
            for row in con.execute(
                "DESCRIBE SELECT * FROM read_parquet(?, union_by_name=true)", [sources]
            ).fetchall()
        }

        source_crs = self._common_crs(con, [sources] if isinstance(sources, str) else sources)
        selections = []
        selected_targets = []
        for k, v in self.columns.items():
            targets = list(v) if isinstance(v, (list, tuple)) else [v]
            if k == "id" and self.index_as_id:
                # 0-based, like the index the GeoDataFrame-based codepath assigns
                selections.append('(row_number() OVER () - 1) AS "id"')
                selected_targets.append("id")
                continue
            if k not in available:
                self.warning(f"Column '{k}' not found in dataset, removing from schema")
                continue
            expr = self.column_migrations.get(k, f'"{k}"')
            for target in targets:
                selections.append(f'{expr} as "{target}"')
                selected_targets.append(target)

        collection = self.create_collection(cid)
        collection["collection"] = cid

        # A constant the schema pins to the feature level becomes a literal column and one
        # it pins to the collection goes there; the rest follow `dehydrate`, like the
        # dehydration step of the GeoDataFrame-based codepath
        if self.column_additions:
            context = collection.get_collection_context()
            for key, value in self.column_additions.items():
                # constants override equally named source columns
                if key in selected_targets:
                    keep = [i for i, t in enumerate(selected_targets) if t != key]
                    selections = [selections[i] for i in keep]
                    selected_targets = [selected_targets[i] for i in keep]
                where = context.get(key)
                if where is True or (where is None and self.dehydrate):
                    collection[key] = value
                else:
                    selections.append(f'{_sql_literal(value)} as "{key}"')
                    selected_targets.append(key)
        selection = ", ".join(selections)

        filters = []
        where = ""
        if self.bbox is not None:
            # The filter runs against the source relation, so it must use the
            # source column that is mapped to the geometry
            geom_source = next(
                (
                    k
                    for k, v in self.columns.items()
                    if "geometry" in (v if isinstance(v, (list, tuple)) else [v])
                ),
                "geometry",
            )
            filters.append(
                f'ST_Intersects("{geom_source}", ST_MakeEnvelope({self.bbox[0]}, {self.bbox[1]}, {self.bbox[2]}, {self.bbox[3]}))'
            )
        for k, v in self.column_filters.items():
            filters.append(v)
        if len(filters) > 0:
            where = f"WHERE {' AND '.join(filters)}"

        if isinstance(sources, str):
            sources_sql = _sql_path(sources)
        else:
            sources_sql = "[" + ",".join(_sql_path(path) for path in sources) + "]"
        source_query = f"""
            SELECT {selection}
            FROM read_parquet({sources_sql}, union_by_name=true)
            {where}
        """

        return self.write_query(
            con,
            source_query,
            output_file,
            collection,
            targets=selected_targets,
            source_crs=source_crs,
            ids_are_generated=self.index_as_id,
            compression=compression,
            compression_level=compression_level,
            geoparquet_version=geoparquet_version,
            original_geometries=original_geometries,
        )

    def _common_crs(self, con, sources: list):
        """The CRS the sources declare, refusing a set that does not agree on one.

        They are combined without reprojection, and DuckDB before 1.5 drops the CRS
        from the metadata, so it has to be read from the files themselves.
        """
        source_crs = None
        reference = None
        for i, source in enumerate(sources):
            crs = None
            row = con.execute(
                "SELECT value FROM parquet_kv_metadata(?) WHERE key = 'geo'", [source]
            ).fetchone()
            if row:
                geo = json.loads(bytes(row[0]))
                primary = geo.get("primary_column", "")
                crs = geo.get("columns", {}).get(primary, {}).get("crs")
            if i == 0:
                source_crs = crs
                reference = _normalize_crs(crs)
            elif not _equal_crs(_normalize_crs(crs), reference):
                raise ValueError(
                    f"The sources use different coordinate reference systems: {source} "
                    "differs from the first source. Reproject the sources to a common CRS."
                )
        return source_crs

    def write_query(
        self,
        con,
        source_query: str,
        output_file,
        collection,
        targets: list,
        source_crs=None,
        # convert() numbers the rows itself, so they are unique by construction; a merge
        # combines parts that each started over, so it always has to check
        ids_are_generated: bool = False,
        compression: Optional[str] = None,
        compression_level: Optional[int] = None,
        geoparquet_version: Optional[str] = None,
        original_geometries: bool = False,
    ) -> str:
        """Write the rows a SELECT returns as a Vecorel GeoParquet file: drop rows
        that no required property or geometry survives, report an id that is not
        unique, normalize the geometries, sort into Hilbert order and package.

        `targets` names the properties the query returns, which is what the checks
        run over.
        """
        compression = compression or "zstd"
        if compression == "zstd" and compression_level is None:
            compression_level = 15
        geoparquet_version = geoparquet_version or "1.1.0"
        row_group_size = GeoParquet.row_group_size
        if isinstance(output_file, Path):
            output_file = str(output_file)
        directory = os.path.dirname(output_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        selected_targets = targets
        collection_json = json.dumps(collection, cls=VecorelJSONEncoder).encode("utf-8")

        # An external sort spills to disk; keep that next to the output, which is
        # where there is room for it, rather than wherever DuckDB defaults to
        con.execute(
            f"SET temp_directory = {_sql_path(os.path.join(os.path.dirname(output_file) or '.', '.duckdb_tmp'))}"
        )

        # Same bounded null-value drop, empty-geometry drop and id uniqueness
        # check as in the GeoDataFrame-based codepath, in one scan
        schemas = collection.merge_schemas({})
        collection_only = set(collection.get_collection_only_properties())
        required = [
            r
            for r in schemas.get("required", [])
            if r != "geometry" and r not in collection_only and r in selected_targets
        ]
        stats = ["count(*)"]
        null_cond = None
        if required:
            null_cond = " OR ".join(f'"{target}" IS NULL' for target in required)
            stats.append(f"count(*) FILTER (WHERE {null_cond})")
        # row numbers are unique by construction
        check_ids = "id" in selected_targets and not ids_are_generated
        if check_ids:
            stats.append('count("id")')
            stats.append('count(DISTINCT "id")')
        blank_cond = None
        if "geometry" in selected_targets:
            blank_cond = '"geometry" IS NULL OR ST_IsEmpty("geometry")'
            stats.append(f"count(*) FILTER (WHERE {blank_cond})")
        if len(stats) > 1:
            values = list(
                con.execute(f"SELECT {', '.join(stats)} FROM ({source_query})").fetchone()
            )
            total = values.pop(0)
            invalid = values.pop(0) if null_cond else 0
            if check_ids:
                non_null = values.pop(0)
                distinct = values.pop(0)
                if distinct < non_null:
                    self.warning(
                        f"{type(self).__name__}: 'id' is not unique — {non_null - distinct:,} "
                        f"of {non_null:,} rows repeat an id, so it cannot be `id`. Map a column "
                        "that identifies a feature, or build one from the source's key columns."
                    )
            blanks = values.pop(0) if blank_cond else 0
            if invalid:
                share = invalid / total
                if share > self.max_dropped_share:
                    raise ValueError(
                        f"{invalid} of {total} rows ({share:.1%}) have no value for a required "
                        f"property ({null_cond}); fix the converter instead of dropping them"
                    )
                self.warning(
                    f"Dropping {invalid} of {total} rows without a value for a "
                    f"required property ({null_cond})"
                )
                source_query = f"SELECT * FROM ({source_query}) WHERE NOT ({null_cond})"
            if blanks:
                share = blanks / total
                message = f"Dropping {blanks} of {total} rows with an empty or missing geometry"
                if share > self.max_dropped_share:
                    message += f" ({share:.1%}, exceeds max_dropped_share) — fix the converter"
                self.warning(message)
                source_query = f"SELECT * FROM ({source_query}) WHERE NOT ({blank_cond})"
        if original_geometries:
            query = source_query
        else:
            # Mirror the geometry handling of the GeoDataFrame-based codepath:
            # make geometries valid, split multi-part geometries, keep only
            # valid polygons, and remove the Z dimension
            query = f"""
              WITH src AS ({source_query}),
              valid AS (
                SELECT * REPLACE (ST_MakeValid(geometry) AS geometry) FROM src
              ),
              parts AS (
                SELECT * EXCLUDE (geometry), UNNEST(ST_Dump(geometry), recursive := true)
                FROM valid
              )
              SELECT * EXCLUDE (geom, path), ST_Force2D(geom) AS geometry
              FROM parts
              WHERE ST_GeometryType(geom) = 'POLYGON' AND ST_IsValid(geom)
            """

        # No ORDER BY here: ST_Hilbert without bounds is meaningless (whole
        # countries collapse into a handful of cells), and with bounds it uses
        # a different reference grid than the rest of the pipeline. The
        # canonical Hilbert sort below runs on the written file.
        con.execute(
            f"""
            COPY ({query}) TO ? (
                FORMAT parquet,
                ROW_GROUP_SIZE {row_group_size},
                compression ?,
                KV_METADATA {{
                    collection: ?,
                }}
            )
        """,
            [output_file, compression, collection_json],
        )

        # Sort against the same CRS-derived Hilbert grid as the
        # GeoDataFrame-based codepath
        with pq.ParquetFile(output_file) as pf:
            meta = pf.schema_arrow.metadata or {}
        if b"geo" in meta:
            geo = json.loads(meta[b"geo"])
            primary = geo["primary_column"]
            crs = geo["columns"][primary].get("crs") or source_crs or "EPSG:4326"
            bounds = hilbert_reference_bounds(crs, geo["columns"][primary].get("bbox"))
            if bounds is None:
                self.warning("CRS declares no area of use; skipping spatial ordering")
            else:
                keys_path, is_sorted = self._write_hilbert_keys(output_file, primary, bounds)
                try:
                    if not is_sorted:
                        self._sort_output(
                            con,
                            output_file,
                            keys_path,
                            compression,
                            collection_json,
                            row_group_size,
                        )
                        self.info("Sorted output into Hilbert order")
                finally:
                    if os.path.exists(keys_path):
                        os.unlink(keys_path)

        gp = GeoParquet(output_file)
        gp.set_collection(collection)
        gp.postprocess(
            compression=compression,
            compression_level=compression_level,
            geoparquet_version=geoparquet_version,
            crs=source_crs,
        )

        return output_file

    def merge_parquet(self, paths: list, output_file, collection=None, **kwargs) -> str:
        """Combine Vecorel GeoParquet files into one, checked and sorted over the
        whole set rather than per file.

        The parts are written by a converter, so they need no column mapping and
        their geometries are already valid polygons; pass `original_geometries=False`
        to run the geometry step anyway.
        """
        if not paths:
            raise ValueError("No paths to merge")
        paths = [str(path) for path in paths]
        kwargs.setdefault("original_geometries", True)

        con = duckdb.connect()
        con.install_extension("spatial")
        con.load_extension("spatial")

        source_crs = self._common_crs(con, paths)

        # union_by_name, because a converter drops a column a source file does not have,
        # so two parts of one dataset can legitimately differ; the targets then come from
        # the union rather than from whichever part happens to be first
        sources = "[" + ",".join(_sql_path(path) for path in paths) + "]"
        source_query = f"SELECT * FROM read_parquet({sources}, union_by_name=true)"
        targets = [row[0] for row in con.execute(f"DESCRIBE {source_query}").fetchall()]

        if collection is None:
            from ..vecorel.ops import merge_collections

            collection = merge_collections(
                [GeoParquet(path).get_collection() for path in paths]
            )

        return self.write_query(
            con,
            source_query,
            output_file,
            collection,
            targets=targets,
            source_crs=source_crs,
            **kwargs,
        )

    # Streams the Hilbert keys per row group to a sidecar file and reports
    # whether the file is already sorted, so memory stays bounded
    def _write_hilbert_keys(self, output_file, primary, bounds):
        directory = os.path.dirname(output_file) or "."
        with NamedTemporaryFile("wb", delete=False, dir=directory, suffix=".parquet") as tmp:
            keys_path = tmp.name
        schema = pa.schema([("hilbert", pa.uint64()), ("ordinal", pa.uint64())])
        is_sorted = True
        last = None
        ordinal = 0
        try:
            writer = pq.ParquetWriter(keys_path, schema)
            try:
                with pq.ParquetFile(output_file) as pf:
                    file_schema = pf.schema_arrow
                    has_bbox = "bbox" in file_schema.names and pa.types.is_struct(
                        file_schema.field("bbox").type
                    )
                    columns = ["bbox"] if has_bbox else [primary]
                    for rg in range(pf.num_row_groups):
                        table = pf.read_row_group(rg, columns=columns)
                        keys = hilbert_keys_for_table(table, primary, bounds)
                        if keys.size:
                            if last is not None and keys[0] < last:
                                is_sorted = False
                            if not bool(np.all(keys[1:] >= keys[:-1])):
                                is_sorted = False
                            last = keys[-1]
                        # The ordinal makes ties keep their original order, like
                        # the stable sort of the GeoDataFrame-based codepath
                        ordinals = np.arange(ordinal, ordinal + keys.size, dtype=np.uint64)
                        ordinal += keys.size
                        writer.write_table(
                            pa.table({"hilbert": keys, "ordinal": ordinals}, schema=schema)
                        )
            finally:
                writer.close()
        except Exception:
            if os.path.exists(keys_path):
                os.unlink(keys_path)
            raise
        return keys_path, is_sorted

    # Rewrites the file in the order given by the Hilbert keys.
    # DuckDB sorts externally (spilling to disk if needed), so this works for
    # datasets that don't fit into memory.
    def _sort_output(
        self, con, output_file, keys_path, compression, collection_json, row_group_size
    ):
        directory = os.path.dirname(output_file) or "."
        tmp_path = None
        try:
            with NamedTemporaryFile("wb", delete=False, dir=directory, suffix=".parquet") as tmp:
                tmp_path = tmp.name

            con.execute(
                f"""
                COPY (
                  SELECT d.*
                  FROM read_parquet({_sql_path(output_file)}) d
                  POSITIONAL JOIN read_parquet({_sql_path(keys_path)}) k
                  ORDER BY k.hilbert, k.ordinal
                ) TO ? (
                    FORMAT parquet,
                    ROW_GROUP_SIZE {row_group_size},
                    compression ?,
                    KV_METADATA {{
                        collection: ?,
                    }}
                )
            """,
                [tmp_path, compression, collection_json],
            )
            os.replace(tmp_path, output_file)
        except Exception:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
