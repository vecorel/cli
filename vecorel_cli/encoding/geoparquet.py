import json
from pathlib import Path
from typing import Optional, Union

import pyarrow as pa
import pyarrow.parquet as pq
from geopandas import GeoDataFrame
from geopandas.io.arrow import _arrow_to_geopandas
from pyarrow import NativeFile
from pyarrow.fs import FSSpecHandler, PyFileSystem

from ..parquet.parquet import create_parquet
from ..util import get_fs, load_file
from .base import BaseEncoding


class GeoParquet(BaseEncoding):
    schema_uri = "https://geoparquet.org/releases/v{version}/schema.json"
    ext = [".parquet", ".geoparquet"]

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

    def get_geoparquet_version(self) -> Optional[str]:
        geo = self.get_metadata(b"geo")
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

    def get_columns(self) -> Optional[dict[str, list[str]]]:
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
    # geoparquet1: bool = False (False => 1.1, True => 1.0)
    # compression: str = None (brotli, snappy, gzip, lz4, zstd, ...)
    def write(self, data: GeoDataFrame, collection: dict = {}, **kwargs) -> bool:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        create_parquet(data, self.file, collection=collection, **kwargs)
        return True

    # kwargs:
    # if num = None => kwargs go into pq.read_table
    # if num is set => kwargs go into pg.ParquetFile
    def read(self, num: int = None, columns: list[str] = None, **kwargs) -> GeoDataFrame:
        if columns is not None or len(columns) == 0:
            columns = None

        if num is None:
            table = pq.read_table(self.pa_file, columns=columns, **kwargs)
        else:
            pf = pq.ParquetFile(self.pa_file, **kwargs)
            rows = next(pf.iter_batches(batch_size=num, columns=columns))
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
