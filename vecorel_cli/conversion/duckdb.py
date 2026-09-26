import base64
import datetime
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..encoding.geojson import VecorelJSONEncoder
from ..encoding.geoparquet import GeoParquet
from ..parquet.types import get_pyarrow_type
from ..vecorel.hilbert import hilbert_keys_for_table, hilbert_reference_bounds
from ..vecorel.ops import get_collection_id, merge_collections, warn_missing_required
from .base import BaseConverter


# COPY doesn't support bound parameters for read_parquet file names,
# so paths are inlined as escaped single-quoted string literals
def _sql_path(path) -> str:
    escaped = str(path).replace("'", "''")
    return f"'{escaped}'"


def _sql_name(name) -> str:
    escaped = str(name).replace('"', '""')
    return f'"{escaped}"'


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


# Collection metadata is JSON, so temporal and binary values are encoded as strings
def _to_arrow_value(value, dtype):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, str):
        if dtype == "date-time":
            ts = pd.Timestamp(value)
            return (
                ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
            ).to_pydatetime()
        if dtype == "date":
            return datetime.date.fromisoformat(value[:10])
        if dtype == "binary":
            return base64.b64decode(value)
    return value


def _constants_table(constants: dict, props: dict) -> pa.Table:
    """A single row with the given values, typed by the property schemas where available."""
    arrays = []
    for key, value in constants.items():
        schema = props.get(key) or {}
        try:
            pa_type = get_pyarrow_type(schema) if schema.get("type") else None
            arrays.append(pa.array([_to_arrow_value(value, schema.get("type"))], type=pa_type))
        except Exception:
            arrays.append(pa.array([value]))
    return pa.table(arrays, names=list(constants.keys()))


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
        self.select_variant(variant)
        cid = self.id.strip()
        if self.bbox is not None and len(self.bbox) != 4:
            raise ValueError("If provided, the bounding box must consist of 4 numbers")

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
        # GeoDataFrame-based codepath does; the types feed the id composition
        available = {
            row[0]: row[1]
            for row in con.execute(
                "DESCRIBE SELECT * FROM read_parquet(?, union_by_name=true)", [sources]
            ).fetchall()
        }

        source_crs = self._common_crs(con, [sources] if isinstance(sources, str) else sources)
        selections = []
        selected_targets = []
        # id_columns wins over an (often inherited) mapping to `id`; two selections
        # would otherwise produce two columns named `id`
        columns = self._drop_id_targets(self.columns) if self.id_columns else self.columns
        for k, v in columns.items():
            targets = list(v) if isinstance(v, (list, tuple)) else [v]
            if k not in available:
                self.warning(f"Column '{k}' not found in dataset, removing from schema")
                continue
            expr = self.column_migrations.get(k, f'"{k}"')
            for target in targets:
                selections.append(f'{expr} as "{target}"')
                selected_targets.append(target)

        # id: composed from id_columns, the column mapped to it, or the row number
        # (0-based, like the GeoDataFrame-based codepath)
        ids_are_generated = False
        if self.id_columns:
            parts = []
            for c in self.id_columns:
                if c in (self.column_additions or {}):
                    # constants are added before the id is composed in the
                    # GeoDataFrame-based codepath, so they can be id parts here too,
                    # with the same formatting for integer-valued floats
                    if c in self.column_migrations:
                        raise ValueError(
                            f"{type(self).__name__}: id_columns '{c}' is a constant with "
                            "a column migration, which this codepath cannot compose"
                        )
                    value = self.column_additions[c]
                    if value is None:
                        # str() would bake the literal "None" into every id; the
                        # GeoDataFrame-based codepath fails on the null ids too
                        raise ValueError(f"id_columns: '{c}' is a null constant")
                    if isinstance(value, float):
                        if not value.is_integer():
                            raise ValueError(f"id_columns: '{c}' has decimal values")
                        value = int(value)
                    parts.append(_sql_literal(str(value)))
                elif c in self.column_migrations:
                    # the id is composed after the column migrations ran; probe the
                    # migrated type so integer-valued floats format the same way
                    expr = f"({self.column_migrations[c]})"
                    sql_type = con.execute(
                        f"DESCRIBE SELECT {expr} AS part FROM read_parquet(?, union_by_name=true)",
                        [sources],
                    ).fetchone()[1]
                    parts.append(self._stringify_sql(expr, sql_type, c))
                elif c in available:
                    parts.append(self._stringify_sql(f'"{c}"', available[c], c))
                else:
                    raise ValueError(f"{type(self).__name__}: id_columns '{c}' not in the data")
            joined = f" || {_sql_literal(self.id_separator)} || ".join(parts)
            selections.append(f'({joined}) AS "id"')
            selected_targets.append("id")
        elif "id" not in selected_targets:
            self.info("No column is mapped to 'id'; numbering the rows")
            selections.append('(row_number() OVER () - 1) AS "id"')
            selected_targets.append("id")
            ids_are_generated = True

        collection = self.create_collection(cid)
        collection["collection"] = cid

        # A constant the schema pins to the feature level becomes a literal column and one
        # it pins to the collection goes there; the rest follow `dehydrate`, like the
        # dehydration step of the GeoDataFrame-based codepath
        if self.column_additions:
            context = collection.get_collection_context()
            for key, value in self.column_additions.items():
                if key == "id" and self.id_columns:
                    # the composed id stays authoritative, like in the
                    # GeoDataFrame-based codepath
                    continue
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
            ids_are_generated=ids_are_generated,
            compression=compression,
            compression_level=compression_level,
            geoparquet_version=geoparquet_version,
            original_geometries=original_geometries,
        )

    @staticmethod
    def _stringify_sql(expr, sql_type, label):
        """A string form for id parts that does not render an integer-typed float
        as '4.0'; a true decimal value is rejected, like _stringify in the
        GeoDataFrame-based codepath."""
        if sql_type in ("FLOAT", "DOUBLE", "REAL"):
            message = _sql_literal(f"id_columns: '{label}' has decimal values")
            return (
                f"CASE WHEN ({expr}) IS NULL THEN NULL "
                f"WHEN trunc({expr}) = ({expr}) "
                f"THEN CAST(CAST(({expr}) AS BIGINT) AS VARCHAR) "
                f"ELSE error({message}) END"
            )
        if sql_type == "BOOLEAN":
            # DuckDB renders true/false; match the GeoDataFrame-based codepath
            return f"CASE WHEN ({expr}) THEN 'True' WHEN NOT ({expr}) THEN 'False' END"
        return f"CAST(({expr}) AS VARCHAR)"

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
        suffix_duplicate_ids: bool = True,
        strict: bool = True,
    ) -> str:
        """Write the rows a SELECT returns as a Vecorel GeoParquet file: drop rows
        that no required property or geometry survives, report an id that is not
        unique, normalize the geometries, sort into Hilbert order and package.

        `targets` names the properties the query returns, which is what the checks
        run over. Ids only need to be unique per collection.
        Without `strict`, a missing required value is only reported and empty
        geometries are kept, as the in-memory merge does.
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

        # Same required-value check, empty-geometry drop and id uniqueness
        # check as in the GeoDataFrame-based codepath, in one scan
        collection_only = set(collection.get_collection_only_properties())
        has_collection_column = "collection" in selected_targets

        def null_condition(schema, skip=("geometry",)):
            required = [
                r
                for r in schema.get("required", [])
                if r not in skip and r not in collection_only and r in selected_targets
            ]
            return " OR ".join(f'"{target}" IS NULL' for target in required) or None

        schema_groups = collection.get_schemas()
        if len(schema_groups) > 1 and has_collection_column:
            # Each collection only requires what its own schemas require
            custom_schemas = collection.get_custom_schemas()
            conditions = ['"collection" IS NULL']
            for cid, group in schema_groups.items():
                schema = group.merge_schemas(custom_schemas=custom_schemas)
                cond = null_condition(schema, skip=("geometry", "collection"))
                if cond:
                    conditions.append(f'("collection" = {_sql_literal(cid)} AND ({cond}))')
            null_cond = " OR ".join(conditions)
        else:
            null_cond = null_condition(collection.merge_schemas({}))
        stats = ["count(*)"]
        if null_cond:
            stats.append(f"count(*) FILTER (WHERE {null_cond})")
        # row numbers are unique by construction
        check_ids = "id" in selected_targets and not ids_are_generated
        if check_ids:
            id_key = (
                'struct_pack(c := "collection", i := "id")' if has_collection_column else '"id"'
            )
            stats.append('count("id")')
            stats.append(f'count(DISTINCT {id_key}) FILTER (WHERE "id" IS NOT NULL)')
        blank_cond = None
        repair_cond = None
        if "geometry" in selected_targets:
            blank_cond = '"geometry" IS NULL OR ST_IsEmpty("geometry")'
            stats.append(f"count(*) FILTER (WHERE {blank_cond})")
            if not original_geometries:
                # Only an invalid or non-polygonal geometry can end up without a
                # polygonal part; count them here so the drop report below can
                # run ST_MakeValid over just those rows instead of everything
                repair_cond = (
                    'NOT ST_IsValid("geometry") OR '
                    "ST_GeometryType(\"geometry\") NOT IN ('POLYGON', 'MULTIPOLYGON')"
                )
                stats.append(f"count(*) FILTER (WHERE NOT ({blank_cond}) AND ({repair_cond}))")
        if len(stats) > 1:
            values = list(
                con.execute(f"SELECT {', '.join(stats)} FROM ({source_query})").fetchone()
            )
            total = values.pop(0)
            invalid = values.pop(0) if null_cond else 0
            if check_ids:
                non_null = values.pop(0)
                distinct = values.pop(0)
                if distinct < non_null and suffix_duplicate_ids:
                    self.warning(
                        f"{type(self).__name__}: 'id' is not unique — {non_null - distinct:,} "
                        f"of {non_null:,} rows repeat an id, so it cannot be `id`. Map a column "
                        "that identifies a feature, or build one from the source's key columns. "
                        "The repeating ids get a ~<n> suffix in the output."
                    )
                elif distinct < non_null:
                    self.warning(
                        f"{non_null - distinct:,} of {non_null:,} rows repeat an id within their collection"
                    )
            blanks = values.pop(0) if blank_cond else 0
            repairs = values.pop(0) if repair_cond else 0
            if invalid and not strict:
                self.warning(
                    f"{invalid} of {total} rows have no value for a required property, "
                    "the merged file will be invalid"
                )
            elif invalid:
                # A null in a required property is an error, whatever the count:
                # the writer rejects nulls in the non-nullable required fields
                # anyway, and silently dropping rows would make that data-quality
                # decision for the user (vecorel/cli#33)
                raise ValueError(
                    f"{invalid} of {total} rows have no value for a required property "
                    f"({null_cond}). Handle them in the converter: fix the mapping, "
                    "fill the values in column_migrations, or exclude the rows with "
                    "a column_filters entry."
                )
            if blanks and strict:
                self.warning(f"Dropping {blanks} of {total} rows with an empty or missing geometry")
                source_query = f"SELECT * FROM ({source_query}) WHERE NOT ({blank_cond})"
            if repairs:
                # a row is dropped when the repair leaves nothing polygonal,
                # like the geometry query below (and the GeoDataFrame codepath)
                dropped = con.execute(
                    f"""
                    SELECT count(*) FROM ({source_query})
                    WHERE ({repair_cond})
                      AND ST_IsEmpty(ST_CollectionExtract(ST_MakeValid(geometry), 3))
                    """
                ).fetchone()[0]
                if dropped:
                    self.warning(
                        f"Dropping {dropped} of {total - blanks} rows without a polygonal geometry"
                    )
        if original_geometries:
            query = source_query
        else:
            # Mirror the geometry handling of the GeoDataFrame-based codepath:
            # make geometries valid, keep only their polygonal parts, and
            # remove the Z dimension
            # The members of a collection may overlap each other — a collection is
            # valid that way — but a MultiPolygon assembled from them is not, so
            # an extraction needs a second ST_MakeValid.
            query = f"""
              WITH src AS ({source_query}),
              valid AS (
                SELECT * REPLACE (ST_MakeValid(geometry) AS geometry) FROM src
              ),
              polygonal AS (
                SELECT * REPLACE (
                  CASE WHEN ST_GeometryType(geometry) = 'GEOMETRYCOLLECTION'
                       THEN ST_MakeValid(ST_CollectionExtract(geometry, 3))
                       ELSE geometry END AS geometry) FROM valid
              )
              SELECT * REPLACE (ST_Force2D(geometry) AS geometry)
              FROM polygonal
              WHERE ST_GeometryType(geometry) IN ('POLYGON', 'MULTIPOLYGON')
                AND NOT ST_IsEmpty(geometry)
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

        if "id" in selected_targets and suffix_duplicate_ids:
            self._suffix_duplicate_ids_in_file(
                con, output_file, compression, collection_json, row_group_size
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

    def _suffix_duplicate_ids_in_file(
        self, con, output_file, compression, collection_json, row_group_size
    ):
        """Number the ids that appear on several rows of a collection (id~1, id~2, ...), like the
        GeoDataFrame-based codepath, when the source does not provide unique ids
        (the pre-write check only warns). Runs on the written file, so the id
        column keeps its type when nothing repeats; the rewrite may reorder rows,
        which the Hilbert sort afterwards puts right. A numbered id can collide
        with one the source already carries (x~1), so this repeats until nothing
        repeats."""
        names = pq.read_schema(output_file).names
        key = '"collection", "id"' if "collection" in names else '"id"'
        reported = False
        while True:
            total, duplicated = con.execute(
                f"""
                SELECT coalesce(sum(n), 0), coalesce(sum(n) FILTER (WHERE n > 1), 0)
                FROM (
                    SELECT count(*) AS n FROM read_parquet({_sql_path(output_file)})
                    WHERE "id" IS NOT NULL GROUP BY {key}
                )
                """
            ).fetchone()
            if not duplicated:
                return
            if not reported:
                self.warning(
                    f"{duplicated:,} of {total:,} rows repeat an id; the ids are numbered "
                    "(id~1, id~2, ...) to keep them unique — the id column becomes a string"
                )
                reported = True
            directory = os.path.dirname(output_file) or "."
            tmp_path = None
            try:
                with NamedTemporaryFile(
                    "wb", delete=False, dir=directory, suffix=".parquet"
                ) as tmp:
                    tmp_path = tmp.name
                con.execute(
                    f"""
                    COPY (
                      SELECT * EXCLUDE (file_row_number) REPLACE (
                        CASE WHEN count(*) OVER (PARTITION BY {key}) > 1
                             THEN CAST("id" AS VARCHAR) || '~' || CAST(
                                  row_number() OVER (PARTITION BY {key} ORDER BY file_row_number)
                                  AS VARCHAR)
                             ELSE CAST("id" AS VARCHAR)
                        END AS "id")
                      FROM read_parquet({_sql_path(output_file)}, file_row_number=true)
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

    def merge_parquet(
        self, paths: list, output_file, collection=None, properties=None, **kwargs
    ) -> str:
        """Combine Vecorel GeoParquet files into one, checked and sorted over the
        whole set rather than per file.

        The parts are written by a converter, so they need no column mapping and
        their geometries are already valid polygons; pass `original_geometries=False`
        to run the geometry step anyway. `properties` restricts the properties that
        are merged. The bbox is always recomputed, as not all parts may have one.
        """
        if not paths:
            raise ValueError("No paths to merge")
        paths = [str(path) for path in paths]
        kwargs.setdefault("original_geometries", True)
        if properties is not None:
            properties = set(properties) | {"geometry"}

        con = duckdb.connect()
        con.install_extension("spatial")
        con.load_extension("spatial")

        source_crs = self._common_crs(con, paths)

        collections = [GeoParquet(path).get_collection() for path in paths]
        if collection is None:
            collection = merge_collections(collections, properties=properties, log=self)
            if properties is not None:
                warn_missing_required(collection, properties, {}, self)
        props = collection.merge_schemas({}).get("properties", {})

        # union by name, because a converter drops a column a source file does not have,
        # so two parts of one dataset can legitimately differ; the targets then come from
        # the union rather than from whichever part happens to be first
        selects = []
        for i, (path, part) in enumerate(zip(paths, collections)):
            names = pq.read_schema(path).names
            collection_only = set(part.get_collection_only_properties())
            # A part keeps its constants in its collection; one the merged collection does not
            # carry, because the parts disagree on it, goes back into the rows, as `vec merge` does
            constants = {
                key: value
                for key, value in part.items()
                if key not in collection
                and key not in collection_only
                and key != "schemas"
                and key not in names
                and (properties is None or key in properties)
            }
            keep_collection = properties is None or "collection" in properties
            fill = None
            if keep_collection and "collection" in names:
                # Fill gaps like the in-memory merge does, if the part's collection is known
                try:
                    fill = get_collection_id(part, path)
                except ValueError:
                    pass
            elif keep_collection and "collection" not in collection:
                # Features of multiple collections must state their collection
                constants["collection"] = get_collection_id(part, path)

            columns = []
            for name in names:
                if name == "bbox" or (properties is not None and name not in properties):
                    continue
                if name == "collection" and fill is not None:
                    columns.append(f'coalesce("collection", {_sql_literal(fill)}) AS "collection"')
                else:
                    columns.append(_sql_name(name))
            query = f"SELECT {', '.join(columns)}"
            source = f"read_parquet({_sql_path(path)})"
            if constants:
                # A registered table rather than SQL literals, so arrays, objects and
                # temporal values keep their types
                table = f"constants_{i}"
                con.register(table, _constants_table(constants, props))
                query += f", {table}.*"
                source += f" CROSS JOIN {table}"
            selects.append(f"{query} FROM {source}")
        source_query = " UNION ALL BY NAME ".join(selects)
        targets = [row[0] for row in con.execute(f"DESCRIBE {source_query}").fetchall()]

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
