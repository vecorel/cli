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
from ..encoding.geojson import VecorelJSONEncoder
from ..parquet.geopandas import to_parquet
from ..parquet.types import get_geopandas_dtype, get_pyarrow_field, get_pyarrow_type_for_geopandas
from ..validation.base import Validator
from ..vecorel.typing import SchemaMapping
from ..vecorel.util import get_fs, load_file
from .base import BaseEncoding


class GeoParquet(BaseEncoding):
    schema_uri = "https://geoparquet.org/releases/v{version}/schema.json"
    ext = [".parquet", ".geoparquet"]
    row_group_size = 25000

    def __init__(self, file: Union[Path, str]):
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

    def _load_collection(self) -> dict:
        return self._parse_metadata(b"collection")

    def get_validator(self) -> Optional[Validator]:
        from ..validation.geoparquet import GeoParquetValidator

        return GeoParquetValidator(self)

    def get_properties(self) -> Optional[dict[str, list[str]]]:
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
        metadata = self.get_parquet_metadata()
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
    # compression: str, optional, default "brotli"
    #     Compression algorithm to use, defaults to "brotli".
    #     Other options are "snappy", "gzip", "lz4", "zstd", etc.
    def write(
        self,
        data: GeoDataFrame,
        properties: Optional[list[str]] = None,
        schema_map: SchemaMapping = {},
        dehydrate: bool = True,
        compression: Optional[str] = None,
        geoparquet_version: Optional[str] = None,
    ) -> bool:
        if compression is None:
            compression = "brotli"

        if geoparquet_version not in GEOPARQUET_VERSIONS:
            geoparquet_version = GEOPARQUET_DEFAULT_VERSION

        self.file.parent.mkdir(parents=True, exist_ok=True)

        if dehydrate:
            data = self.dehydrate_to_collection(data, properties=properties)

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
        schemas = collection.merge_schemas(schema_map)

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
                    self.warning(f"{column}: No type conversion available for {dtype}")
                elif callable(gp_type):
                    data[column] = gp_type(data[column])
                else:
                    data[column] = data[column].astype(gp_type, copy=False)
            except Exception as e:
                self.warning(f"{column}: Can't convert to {dtype}: {e}")

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
                    self.warning(f"{name}: Skipped - {e}")
            else:
                pd_type = str(data[name].dtype)  # pandas data type
                try:
                    pa_type = get_pyarrow_type_for_geopandas(pd_type)  # pyarrow data type
                    if pa_type is not None:
                        self.warning(
                            f"{name}: No schema defined, converting {pd_type} to nullable {pa_type}",
                        )
                        field = get_pyarrow_field(name, pa_type=pa_type)
                    else:
                        self.warning(
                            f"{name}: Skipped - pandas type can't be converted to pyarrow type",
                        )
                        continue
                except Exception as e:
                    self.warning(f"{name}: Skipped - {e}")
                    continue

            if field is None:
                self.warning(f"{name}: Skipped - invalid data type")
                continue
            else:
                pq_fields.append(field)

        # Define the schema for the Parquet file
        pq_schema = pa.schema(pq_fields)
        pq_schema = pq_schema.with_metadata(
            {
                "collection": json.dumps(self.get_collection(), cls=VecorelJSONEncoder).encode(
                    "utf-8"
                )
            }
        )

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
            schema_version=geoparquet_version,
            row_group_size=self.row_group_size,
            write_covering_bbox=bool(geoparquet_version != "1.0.0"),
        )

        return True

    # kwargs:
    # if num = None => kwargs go into pq.read_table
    # if num is set => kwargs go into pg.ParquetFile
    def read(
        self,
        num: Optional[int] = None,
        properties: Optional[list[str]] = None,
        schema_map: SchemaMapping = {},
        hydrate: bool = False,
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
            gdf = self.hydrate_from_collection(gdf)

        return gdf

    def _get_pyarrow_file(self) -> NativeFile:
        filepath = str(self.file)
        fs = get_fs(filepath)
        pyarrow_fs = PyFileSystem(FSSpecHandler(fs))
        return pyarrow_fs.open_input_file(filepath)

    def _parse_metadata(self, key) -> Optional[dict]:
        metadata = self.get_metadata()
        if key in metadata:
            return json.loads(metadata[key].decode("utf-8"))
        else:
            return None
