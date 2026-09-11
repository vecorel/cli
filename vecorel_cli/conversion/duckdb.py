import json
import os
from pathlib import Path
from typing import Optional

import duckdb
import pyarrow.parquet as pq

from ..encoding.geojson import VecorelJSONEncoder
from ..encoding.geoparquet import GeoParquet
from ..vecorel.hilbert import ensure_hilbert_sorted, hilbert_reference_bounds
from .base import BaseConverter


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
        geoparquet_version = geoparquet_version or "1.1.0"
        # Same packaging as the GeoDataFrame-based codepath
        compression = compression or "zstd"
        if compression == "zstd" and compression_level is None:
            compression_level = 15
        row_group_size = GeoParquet.row_group_size

        self.variant = variant
        cid = self.id.strip()
        if self.bbox is not None and len(self.bbox) != 4:
            raise ValueError("If provided, the bounding box must consist of 4 numbers")

        self._check_id_mapping()
        self._require_one_source_of_urls()
        self._prewarm_schemas()

        # Create output folder if it doesn't exist
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

        selections = []
        for k, v in self.columns.items():
            if k in self.column_migrations:
                selections.append(f'{self.column_migrations.get(k)} as "{v}"')
            else:
                selections.append(f'"{k}" as "{v}"')
        selection = ", ".join(selections)

        filters = []
        where = ""
        if self.bbox is not None:
            filters.append(
                f"ST_Intersects(geometry, ST_MakeEnvelope({self.bbox[0]}, {self.bbox[1]}, {self.bbox[2]}, {self.bbox[3]}))"
            )
        for k, v in self.column_filters.items():
            filters.append(v)
        if len(filters) > 0:
            where = f"WHERE {' AND '.join(filters)}"

        if isinstance(urls, str):
            sources = f'"{urls}"'
        else:
            paths = []
            for url in urls:
                if isinstance(url, tuple):
                    paths.append(f'"{url[0]}"')
                else:
                    paths.append(f'"{url}"')
            sources = "[" + ",".join(paths) + "]"

        collection = self.create_collection(cid)
        collection.update(self.column_additions)
        collection["collection"] = self.id

        if isinstance(output_file, Path):
            output_file = str(output_file)

        collection_json = json.dumps(collection, cls=VecorelJSONEncoder).encode("utf-8")

        source_query = f"""
            SELECT {selection}
            FROM read_parquet({sources}, union_by_name=true)
            {where}
        """
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

        con = duckdb.connect()
        con.install_extension("spatial")
        con.load_extension("spatial")
        # No ORDER BY here: ST_Hilbert without bounds is meaningless (whole
        # countries collapse into a handful of cells), and with bounds it uses
        # a different reference grid than the rest of the pipeline. The
        # canonical in-place Hilbert sort below runs after post-processing.
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

        # Post-process the written Parquet file to a compliant GeoParquet file
        # (canonical data types, nullability, bbox column, metadata)
        gp = GeoParquet(output_file)
        gp.set_collection(collection)
        try:
            gp.postprocess(
                compression=compression,
                compression_level=compression_level,
                geoparquet_version=geoparquet_version,
            )
        except Exception as e:
            self.warning(f"GeoParquet post-processing failed: {e}")

        # Canonical spatial ordering against the CRS-derived Hilbert grid,
        # the same grid the GeoDataFrame-based converter sorts against
        with pq.ParquetFile(output_file) as pf:
            meta = pf.schema_arrow.metadata or {}
        if b"geo" in meta:
            geo = json.loads(meta[b"geo"])
            primary = geo["primary_column"]
            crs = geo["columns"][primary].get("crs") or "EPSG:4326"
            bounds = hilbert_reference_bounds(crs, geo["columns"][primary].get("bbox"))
            if bounds is None:
                self.warning("CRS declares no area of use; skipping spatial ordering")
            elif ensure_hilbert_sorted(
                output_file,
                primary,
                bounds,
                compression,
                compression_level,
                row_group_size=row_group_size,
            ):
                self.info("Sorted output into Hilbert order")

        return output_file
