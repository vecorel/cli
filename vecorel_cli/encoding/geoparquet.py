import json
from pathlib import Path
from typing import Optional, Union

import pyarrow as pa
import pyarrow.parquet as pq
from geopandas import GeoDataFrame
from geopandas.io.arrow import _arrow_to_geopandas
from pyarrow import NativeFile
from pyarrow.fs import FSSpecHandler, PyFileSystem

from ..const import GEOPARQUET_DEFAULT_VERSION, GEOPARQUET_VERSIONS
from ..jsonschema.util import is_schema_empty, merge_schemas
from ..parquet.geopandas import to_parquet
from ..parquet.types import get_geopandas_dtype, get_pyarrow_field, get_pyarrow_type_for_geopandas
from ..vecorel.schemas import Schemas
from ..vecorel.util import get_fs, load_file
from ..vecorel.version import vecorel_version
from .base import BaseEncoding


class GeoParquet(BaseEncoding):
    schema_uri = "https://geoparquet.org/releases/v{version}/schema.json"
    ext = [".parquet", ".geoparquet"]
    row_group_size = 25000

    def __init__(self, file: Union[Path, str, NativeFile]):
        self.file: Optional[Path] = None
        self.pq_metadata = None
        self.pq_schema = None

        if not isinstance(file, NativeFile):
            self.file = Path(file)
            self.pa_file = self._get_pyarrow_file(file)
        else:
            self.pa_file = file

    def get_summary(self) -> dict:
        summary = super().get_summary()
        metadata = self.get_pq_metadata()
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

    def get_geoparquet_schema(self) -> Optional[str]:
        version = self.get_geoparquet_version()
        if version is None:
            return None
        return load_file(GeoParquet.schema_uri.format(version=version))

    def get_format(self) -> str:
        geo = self._parse_metadata(b"geo")
        if geo is None:
            return "Parquet"
        else:
            version = geo.get("version", "unknown")
            return f"GeoParquet, version {version}"

    def get_collection(self) -> dict:
        collection = self._parse_metadata(b"collection")
        return collection if collection else {}

    def get_properties(self) -> Optional[dict[str, list[str]]]:
        schema = self.get_pq_schema()
        if schema is None:
            return None
        columns = {}
        for field in schema:
            types = [str(field.type)]
            if field.nullable:
                types.append("null")
            columns[field.name] = types
        return columns

    def get_metadata(self) -> dict:
        metadata = self.get_pq_metadata()
        return metadata.to_dict()

    def get_pq_metadata(self) -> pq.FileMetaData:
        if self.pq_metadata is None:
            self.pq_metadata = pq.read_metadata(self.pa_file)

        return self.pq_metadata

    def get_pq_schema(self) -> pq.ParquetSchema:
        if self.pq_schema is None:
            self.pq_schema = pq.read_schema(self.pa_file)

        return self.pq_schema

    # kwargs:
    #   geoparquet_version: bool, optional, default False
    #       If True, writes the data in GeoParquet 1.0.0 format,
    #       otherwise in GeoParquet 1.1.0 format.
    #   compression: str, optional, default "brotli"
    #       Compression algorithm to use, defaults to "brotli".
    #       Other options are "snappy", "gzip", "lz4", "zstd", etc.
    def write(
        self,
        data: GeoDataFrame,
        collection: dict = {},
        properties: Optional[list[str]] = None,
        schema_map: dict = {},
        missing_schemas: dict = {},
        **kwargs,
    ) -> bool:
        compression = kwargs.get("compression")
        if compression is None:
            compression = "brotli"

        gp_version = kwargs.get("geoparquet_version")
        if gp_version not in GEOPARQUET_VERSIONS:
            gp_version = GEOPARQUET_DEFAULT_VERSION

        self.file.parent.mkdir(parents=True, exist_ok=True)

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
        vecorel_schema = load_file(Schemas.spec_schema.format(version=vecorel_version))
        schemas = merge_schemas(missing_schemas, vecorel_schema)

        # Add the custom schemas to the collection for future use
        if not is_schema_empty(missing_schemas):
            collection = collection.copy()
            collection["custom_schemas"] = missing_schemas

        # todo: Load all extension schemas
        extensions = {}
        if "schemas" in collection and isinstance(collection["schemas"], list):
            for ext in collection["schemas"]:
                try:
                    if ext in schema_map and schema_map[ext] is not None:
                        path = schema_map[ext]
                    else:
                        path = ext
                    extensions[ext] = load_file(path)
                    schemas = merge_schemas(schemas, extensions[ext])
                except Exception as e:
                    self.log(f"Extension schema for {ext} can't be loaded: {e}", "warning")

        # Update the GeoDataFrame with the correct types etc.
        props = schemas.get("properties", {})
        required_props = schemas.get("required", [])
        for column in properties:
            if column not in props:
                continue
            schema = props[column]
            dtype = schema.get("type")
            if dtype == "geometry":
                continue

            required = column in required_props
            gp_type = get_geopandas_dtype(dtype, required, schema)
            try:
                if gp_type is None:
                    self.log(f"{column}: No type conversion available for {dtype}", "warning")
                elif callable(gp_type):
                    data[column] = gp_type(data[column])
                else:
                    data[column] = data[column].astype(gp_type, copy=False)
            except Exception as e:
                self.log(f"{column}: Can't convert to {dtype}: {e}", "warning")

        _columns = list(data.columns)
        duplicates = set([x for x in _columns if _columns.count(x) > 1])
        if len(duplicates):
            raise ValueError(f"Columns are defined multiple times: {duplicates}")

        # Define the fields for the schema
        pq_fields = []
        for name in properties:
            required_props = schemas.get("required", [])
            props = schemas.get("properties", {})
            required = name in required_props
            field = None
            if name in props:
                prop_schema = props[name]
                try:
                    field = get_pyarrow_field(name, schema=prop_schema, required=required)
                except Exception as e:
                    self.log(f"{name}: Skipped - {e}", "warning")
            else:
                pd_type = str(data[name].dtype)  # pandas data type
                try:
                    pa_type = get_pyarrow_type_for_geopandas(pd_type)  # pyarrow data type
                    if pa_type is not None:
                        self.log(
                            f"{name}: No schema defined, converting {pd_type} to nullable {pa_type}",
                            "warning",
                        )
                        field = get_pyarrow_field(name, pa_type=pa_type)
                    else:
                        self.log(
                            f"{name}: Skipped - pandas type can't be converted to pyarrow type",
                            "warning",
                        )
                        continue
                except Exception as e:
                    self.log(f"{name}: Skipped - {e}", "warning")
                    continue

            if field is None:
                self.log(f"{name}: Skipped - invalid data type", "warning")
                continue
            else:
                pq_fields.append(field)

        # Define the schema for the Parquet file
        pq_schema = pa.schema(pq_fields)
        pq_schema = pq_schema.with_metadata({"fiboa": json.dumps(collection).encode("utf-8")})

        if compression is None:
            compression = "brotli"

        # Write the data to the Parquet file
        to_parquet(
            data,
            self.file,
            schema=pq_schema,
            index=False,
            coerce_timestamps="ms",
            compression=compression,
            schema_version=gp_version,
            row_group_size=self.row_group_size,
            write_covering_bbox=bool(gp_version != "1.0.0"),
        )

        return True

    # kwargs:
    # if num = None => kwargs go into pq.read_table
    # if num is set => kwargs go into pg.ParquetFile
    def read(
        self, num: Optional[int] = None, properties: Optional[list[str]] = None, **kwargs
    ) -> GeoDataFrame:
        if properties is not None and len(properties) == 0:
            properties = None

        if num is None:
            table = pq.read_table(self.pa_file, columns=properties, **kwargs)
        else:
            pf = pq.ParquetFile(self.pa_file, **kwargs)
            rows = next(pf.iter_batches(batch_size=num, columns=properties))
            table = pa.Table.from_batches([rows])

        return _arrow_to_geopandas(table)

    def _get_pyarrow_file(self, file: Union[Path, str]) -> NativeFile:
        if isinstance(file, Path):
            file = str(file)
        pyarrow_fs = PyFileSystem(FSSpecHandler(get_fs(file)))
        return pyarrow_fs.open_input_file(file)

    def _parse_metadata(self, key) -> Optional[dict]:
        metadata = self.get_pq_metadata().to_dict()
        if key in metadata:
            return json.loads(metadata[key].decode("utf-8"))
        else:
            return None
