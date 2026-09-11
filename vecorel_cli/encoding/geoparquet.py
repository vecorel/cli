import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional, Union

import pyarrow as pa
import pyarrow.parquet as pq
from geopandas import GeoDataFrame
from geopandas.array import from_wkb
from geopandas.io.arrow import _arrow_to_geopandas
from pyarrow import NativeFile, StructArray
from pyarrow.fs import FSSpecHandler, PyFileSystem
from yarl import URL

from ..const import GEOPARQUET_DEFAULT_VERSION, GEOPARQUET_VERSIONS
from ..encoding.geojson import VecorelJSONEncoder
from ..parquet.geopandas import to_parquet
from ..parquet.types import (
    get_geopandas_dtype,
    get_pyarrow_field,
    get_pyarrow_type,
    get_pyarrow_type_for_geopandas,
    normalize_pa_type,
)
from ..validation.base import Validator
from ..vecorel.typing import SchemaMapping
from ..vecorel.util import get_fs, load_file
from .base import BaseEncoding


class GeoParquet(BaseEncoding):
    schema_uri = "https://geoparquet.org/releases/v{version}/schema.json"
    ext = [".parquet", ".geoparquet"]
    media_type = "application/vnd.apache.parquet"
    row_group_size = 25000

    def __init__(self, file: Union[Path, URL, str]):
        super().__init__(file)
        self.pq_metadata = None
        self.pq_schema = None

    def get_summary(self) -> dict:
        summary = super().get_summary()
        metadata = self.get_parquet_metadata()
        summary["Columns"] = metadata.num_columns
        summary["Rows"] = metadata.num_rows
        summary["Row Groups"] = metadata.num_row_groups
        return summary

    def get_geoparquet_metadata(self) -> Optional[dict]:
        return self._parse_metadata(b"geo")

    def get_geoparquet_version(self) -> Optional[str]:
        geo = self.get_geoparquet_metadata()
        if geo is not None:
            return geo.get("version")
        return None

    def get_geoparquet_schema(self) -> Optional[dict]:
        version = self.get_geoparquet_version()
        if version is None:
            return None
        return load_file(URL(GeoParquet.schema_uri.format(version=version)))

    def get_format(self) -> str:
        geo = self._parse_metadata(b"geo")
        if geo is None:
            return "Parquet"
        else:
            version = geo.get("version", "unknown")
            return f"GeoParquet, version {version}"

    def _load_collection(self) -> dict:
        collection = None
        if self.fs.exists(self.uri):
            collection = self._parse_metadata(b"collection")
        return collection if collection is not None else {}

    def get_validator(self) -> Optional[Validator]:
        from ..validation.geoparquet import GeoParquetValidator

        return GeoParquetValidator(self)

    def get_properties(self) -> dict[str, list[str]]:
        schema = self.get_parquet_schema().to_arrow_schema()
        columns = {}
        for name in schema.names:
            field = schema.field(name)
            types = [str(field.type)]
            if field.nullable:
                types.append("null")
            columns[name] = types
        return columns

    def get_metadata(self) -> dict:
        schema = self.get_parquet_schema().to_arrow_schema()
        return schema.metadata

    def _get_pg_file(self) -> pq.ParquetFile:
        pa_file = self._get_pyarrow_file()
        return pq.ParquetFile(pa_file)

    def get_parquet_metadata(self) -> pq.FileMetaData:
        if self.pq_metadata is None:
            pg_file = self._get_pg_file()
            self.pq_metadata = pg_file.metadata

        return self.pq_metadata

    def get_parquet_schema(self) -> pq.ParquetSchema:
        if self.pq_schema is None:
            pg_file = self._get_pg_file()
            self.pq_schema = pg_file.schema

        return self.pq_schema

    def get_compression(self) -> Optional[str]:
        """
        Get the compression method used in the file.
        Returns "mixed" if multiple compression methods are found.
        """
        return self._detect_compression(self.get_parquet_metadata())

    @staticmethod
    def _detect_compression(metadata: pq.FileMetaData) -> Optional[str]:
        if metadata.num_row_groups == 0:
            return None

        compressions = set()
        row_group = metadata.row_group(0)
        for col_idx in range(row_group.num_columns):
            column = row_group.column(col_idx)
            compression = column.compression
            if compression != "UNCOMPRESSED":
                compressions.add(compression.lower())

        if len(compressions) == 0:
            return None
        elif len(compressions) == 1:
            return next(iter(compressions))
        else:
            return "mixed"

    # geoparquet_version: bool, optional, default False
    #     If True, writes the data in GeoParquet 1.0.0 format,
    #     otherwise in GeoParquet 1.1.0 format.
    # compression: str, optional, default "zstd"
    #     Compression algorithm to use, defaults to "zstd".
    #     Other options are "snappy", "gzip", "lz4", "brotli", etc.
    def write(
        self,
        data: GeoDataFrame,
        properties: Optional[list[str]] = None,
        schema_map: SchemaMapping = {},
        dehydrate: bool = True,
        compression: Optional[str] = "zstd",
        compression_level: Optional[int] = None,  # default level for compression
        geoparquet_version: Optional[str] = None,
        **kwargs,  # capture unknown arguments
    ) -> bool:
        if compression == "zstd" and compression_level is None:
            compression_level = 15
        if geoparquet_version not in GEOPARQUET_VERSIONS:
            geoparquet_version = GEOPARQUET_DEFAULT_VERSION
        self.uri.parent.mkdir(parents=True, exist_ok=True)

        if dehydrate:
            data = self.dehydrate_to_collection(data, properties=properties, schema_map=schema_map)

        if properties is None:
            properties = list(data.columns)
        else:
            # Restrict to the properties that actually exist, ignore all others
            properties = list(set(properties) & set(data.columns))

        # Don't write the bbox properties, will be added automatically later
        if "bbox" in properties:
            del data["bbox"]
            properties.remove("bbox")

        # Load the data schema
        collection = self.get_collection()
        schemas_per_collection = collection.get_schemas()
        has_multiple_collections = len(schemas_per_collection) > 1
        schemas = collection.merge_schemas(schema_map)

        # Update the GeoDataFrame with the correct types and create the parquet schema
        props = schemas.get("properties", {})
        required_props = schemas.get("required", [])
        pq_fields = []
        for column in properties:
            required = column in required_props and not has_multiple_collections
            schema = props.get(column, {})
            dtype = schema.get("type")

            # Convert the data types in the GeoDataFrame
            if dtype is not None:
                gp_type = get_geopandas_dtype(dtype, required, schema)
                if gp_type is None:
                    self.warning(f"{column}: No type conversion available for {dtype}")
                else:
                    try:
                        if callable(gp_type):
                            data[column] = gp_type(data[column])
                        else:
                            data[column] = data[column].astype(gp_type)
                    except Exception as e:
                        self.warning(f"{column}: Can't convert to {dtype}: {e}")

            # Create the Parquet schema
            field = None
            if dtype is not None:
                try:
                    field = get_pyarrow_field(column, schema=schema, required=required)
                except Exception as e:
                    self.warning(f"{column}: Skipped - {e}")
            else:
                pd_type = str(data[column].dtype)  # pandas data type
                try:
                    pa_type = get_pyarrow_type_for_geopandas(pd_type)  # pyarrow data type
                    if pa_type is not None:
                        self.warning(
                            f"{column}: No schema defined, converting {pd_type} to nullable {pa_type}",
                        )
                        field = get_pyarrow_field(column, pa_type=pa_type)
                    else:
                        self.warning(
                            f"{column}: Skipped - pandas type can't be converted to pyarrow type",
                        )
                        continue
                except Exception as e:
                    self.warning(f"{column}: Skipped - {e}")
                    continue

            if field is None:
                self.warning(f"{column}: Skipped - invalid data type")
                continue
            else:
                pq_fields.append(field)

        _columns = list(data.columns)
        duplicates = {x for x in _columns if _columns.count(x) > 1}
        if len(duplicates):
            raise ValueError(f"Columns are defined multiple times: {duplicates}")

        # Define the schema for the Parquet file
        pq_schema = pa.schema(pq_fields)
        pq_schema = pq_schema.with_metadata(
            {
                "collection": json.dumps(self.get_collection(), cls=VecorelJSONEncoder).encode(
                    "utf-8"
                )
            }
        )

        # Write the data to the Parquet file
        to_parquet(
            data,
            self.uri,
            schema=pq_schema,
            index=False,
            coerce_timestamps="ms",
            compression=compression,
            schema_version=geoparquet_version,
            row_group_size=self.row_group_size,
            write_covering_bbox=bool(geoparquet_version != "1.0.0"),
            compression_level=compression_level,
        )

        return True

    def postprocess(
        self,
        schema_map: SchemaMapping = {},
        compression: Optional[str] = None,
        compression_level: Optional[int] = None,
        geoparquet_version: Optional[str] = None,
        crs=None,  # the CRS to record in the GeoParquet metadata, e.g. from the source file
        **kwargs,  # capture unknown arguments
    ) -> bool:
        """
        Rewrites an existing Parquet file (e.g. written by an external tool such as
        DuckDB or GDAL) into a compliant Vecorel GeoParquet file:

        - Converts the column data types to the types defined in the Vecorel schemas,
          otherwise normalizes them to the canonical Vecorel types
          (e.g. large_string -> string, timestamps -> timestamp[ms, UTC])
        - Sets the nullability based on the required properties
        - Adds a bbox covering column for GeoParquet > 1.0.0
        - Updates the GeoParquet metadata and embeds the collection metadata

        The collection metadata is taken from `set_collection` or read from the file.
        The file is rewritten row group by row group, so it never needs to fit into memory.
        If no compression is given, the compression of the existing file is used.

        Checks the file first and only rewrites when something needs to change,
        so it is cheap to call on files that are already compliant.
        Returns True if the file was rewritten, False if it was compliant already.
        """
        if not isinstance(self.uri, Path):
            raise ValueError("Post-processing is only supported for local files")
        if geoparquet_version not in GEOPARQUET_VERSIONS:
            geoparquet_version = GEOPARQUET_DEFAULT_VERSION

        tmp_path = None
        try:
            # The reader must be closed before the temp file can replace the original file,
            # as Windows can't replace files that are still opened
            with pq.ParquetFile(str(self.uri)) as pq_file:
                existing_compression = self._detect_compression(pq_file.metadata)
                if compression is None:
                    compression = existing_compression
                if compression == "mixed":  # per-column codecs are not preserved
                    compression = "zstd"
                if compression == "zstd" and compression_level is None:
                    compression_level = 15
                tmp_path = self._rewrite(
                    pq_file,
                    schema_map,
                    compression,
                    compression_level,
                    geoparquet_version,
                    crs=crs,
                    compression_changed=compression != existing_compression,
                )
            if tmp_path is None:
                return False
            os.replace(tmp_path, self.uri)
        except Exception:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

        # The file has changed, invalidate the cached metadata
        self.pq_metadata = None
        self.pq_schema = None
        return True

    # Rewrites the Parquet file to a temp file and returns its path,
    # or returns None if the file needs no changes
    def _rewrite(
        self,
        pq_file: pq.ParquetFile,
        schema_map: SchemaMapping,
        compression: Optional[str],
        compression_level: Optional[int],
        geoparquet_version: str,
        crs=None,
        compression_changed: bool = False,
    ) -> Optional[str]:
        existing_schema = pq_file.schema_arrow
        col_names = existing_schema.names
        assert "geometry" in col_names, "Missing geometry column in the Parquet file"

        collection = self.get_collection()
        schemas = collection.merge_schemas(schema_map)
        has_multiple_collections = len(collection.get_schemas()) > 1
        props = schemas.get("properties", {})

        # Must mirror the nullability rule of writer and validator:
        # nullable = not required, and everything is nullable for files
        # with multiple collections
        required_columns = set()
        if not has_multiple_collections:
            required_columns = {"geometry"}
            if "id" in col_names:
                required_columns.add("id")
            required_columns |= {r for r in schemas.get("required", []) if r in col_names}

        if "bbox" in col_names:
            bbox_type = existing_schema.field("bbox").type
            children = (
                {bbox_type.field(i).name for i in range(bbox_type.num_fields)}
                if pa.types.is_struct(bbox_type)
                else set()
            )
            if children != {"xmin", "ymin", "xmax", "ymax"}:
                raise ValueError(
                    f"The bbox column is not a GeoParquet covering struct, is {bbox_type}"
                )
        add_bbox = geoparquet_version != "1.0.0" and "bbox" not in col_names

        metadata = existing_schema.metadata or {}
        if b"geo" not in metadata:
            # Creating GeoParquet metadata from scratch would require CRS and
            # geometry information this file doesn't carry
            raise ValueError("The Parquet file has no GeoParquet metadata")
        metadata[b"collection"] = json.dumps(collection, cls=VecorelJSONEncoder).encode("utf-8")
        geo = json.loads(metadata[b"geo"])
        geo["version"] = geoparquet_version
        column = geo.get("columns", {}).get(geo.get("primary_column", "geometry"))
        if column is not None:
            if crs is not None:
                column["crs"] = crs
            if geoparquet_version == "1.0.0":
                # covering metadata only exists since GeoParquet 1.1
                column.pop("covering", None)
            elif add_bbox or "bbox" in col_names:
                column["covering"] = {
                    "bbox": {
                        "xmin": ["bbox", "xmin"],
                        "ymin": ["bbox", "ymin"],
                        "xmax": ["bbox", "xmax"],
                        "ymax": ["bbox", "ymax"],
                    }
                }
        metadata[b"geo"] = json.dumps(geo).encode("utf-8")

        # The bbox covering column is kept as written (a float64 struct, like the
        # GeoDataFrame-based codepath writes it), not as the schema's bounding-box type
        new_fields = []
        for field in existing_schema:
            pa_type = None
            prop_schema = props.get(field.name) if field.name != "bbox" else None
            if prop_schema is not None:
                try:
                    pa_type = get_pyarrow_type(prop_schema)
                except Exception as e:
                    self.warning(f"{field.name}: Can't create data type from schema: {e}")
            if pa_type is None:
                pa_type = normalize_pa_type(field.type)
            new_fields.append(
                pa.field(
                    field.name,
                    pa_type,
                    nullable=field.name not in required_columns,
                    metadata=field.metadata,
                )
            )

        if add_bbox:
            new_fields.append(
                pa.field(
                    "bbox",
                    pa.struct(
                        [
                            ("xmin", pa.float64()),
                            ("ymin", pa.float64()),
                            ("xmax", pa.float64()),
                            ("ymax", pa.float64()),
                        ]
                    ),
                )
            )
        new_schema = pa.schema(new_fields, metadata=metadata)

        if (
            not add_bbox
            and not compression_changed
            and new_schema.equals(existing_schema, check_metadata=True)
        ):
            return None

        with NamedTemporaryFile("wb", delete=False, dir=self.uri.parent, suffix=".parquet") as tmp:
            tmp_path = tmp.name

        try:
            writer = pq.ParquetWriter(
                tmp_path,
                new_schema,
                compression=compression,
                compression_level=compression_level,
                use_dictionary=True,
                write_statistics=True,
            )
            try:
                for rg in range(pq_file.num_row_groups):
                    tbl = pq_file.read_row_group(rg)
                    if add_bbox:
                        # array of shape (n, 4) with minx, miny, maxx, maxy
                        bounds = from_wkb(tbl["geometry"]).bounds
                        bbox_array = StructArray.from_arrays(
                            [bounds[:, 0], bounds[:, 1], bounds[:, 2], bounds[:, 3]],
                            names=["xmin", "ymin", "xmax", "ymax"],
                        )
                        tbl = tbl.append_column("bbox", bbox_array)
                    # The safe cast fails on lossy conversions (e.g. out-of-range integers),
                    # so invalid source data is reported instead of silently corrupted
                    if tbl.schema != new_schema:
                        tbl = tbl.cast(new_schema)
                    writer.write_table(tbl)
            finally:
                writer.close()
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

        return tmp_path

    # kwargs:
    # if num = None => kwargs go into pq.read_table
    # if num is set => kwargs go into pg.ParquetFile
    def read(
        self,
        num: Optional[int] = None,
        properties: Optional[list[str]] = None,
        schema_map: SchemaMapping = {},
        hydrate: bool = False,
        **kwargs,
    ) -> GeoDataFrame:
        if properties is not None and len(properties) == 0:
            properties = None

        if properties is not None:
            # Make sure we ignore properties that don't exist
            existing_properties = set(self.get_properties().keys())
            properties = list(set(properties) & existing_properties)

        if num is None:
            pa_file = self._get_pyarrow_file()
            table = pq.read_table(pa_file, columns=properties)
        else:
            pf = self._get_pg_file()
            rows = next(pf.iter_batches(batch_size=num, columns=properties))
            table = pa.Table.from_batches([rows])

        gdf = _arrow_to_geopandas(table)

        if hydrate:
            gdf = self.hydrate_from_collection(gdf, schema_map=schema_map)

        return gdf

    def _get_pyarrow_file(self) -> NativeFile:
        filepath = str(self.uri)
        fs = get_fs(filepath)
        pyarrow_fs = PyFileSystem(FSSpecHandler(fs))
        return pyarrow_fs.open_input_file(filepath)

    def _parse_metadata(self, key) -> Optional[dict]:
        metadata = self.get_metadata()
        if key in metadata:
            return json.loads(metadata[key].decode("utf-8"))
        else:
            return None
