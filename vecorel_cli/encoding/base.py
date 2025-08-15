from pathlib import Path
from typing import Optional, Union

from fsspec import AbstractFileSystem
from geopandas import GeoDataFrame
from yarl import URL

from ..cli.logger import LoggerMixin
from ..validation.base import Validator
from ..vecorel.collection import Collection
from ..vecorel.typing import SchemaMapping
from ..vecorel.util import format_filesize, get_fs


class BaseEncoding(LoggerMixin):
    ext = []
    media_type = "application/octet-stream"

    def __init__(self, uri: Union[Path, URL, str]):
        if isinstance(uri, str):
            uri = Path(uri)
        self.uri: Union[Path, URL] = uri
        self.fs: AbstractFileSystem = get_fs(uri)
        self.collection: Optional[Collection] = None

    def get_format(self) -> str:
        return "unknown"

    def get_summary(self) -> dict:
        """
        Summarize key statistics quickly for human consumption.
        """
        return {
            "Format": self.get_format(),
            "Size": format_filesize(self.fs.size(self.uri)),
            "Compression": self.get_compression() or "None",
        }

    def _load_collection(self) -> dict:
        return {}

    def get_collection(self) -> Collection:
        """
        Get the collection metadata.
        """
        if self.collection is None:
            self.collection = Collection(self._load_collection())
        return self.collection

    def set_collection(self, collection: Union[Collection, dict]):
        if not isinstance(collection, Collection):
            collection = Collection(collection)

        self.collection = collection

    def get_validator(self) -> Optional[Validator]:
        return None

    def get_properties(self) -> Optional[dict[str, list[str]]]:
        return None

    def get_compression(self) -> Optional[str]:
        """
        Get the compression method used in the file.
        """
        return None

    def exists(self) -> bool:
        return self.fs.exists(self.uri)

    def get_metadata(self) -> dict:
        return {}

    def write(
        self,
        data: GeoDataFrame,
        properties: Optional[list[str]] = None,
        schema_map: SchemaMapping = {},
        dehydrate: bool = True,
        **kwargs,
    ) -> bool:
        raise NotImplementedError("Subclasses must implement this method")

    def read(
        self,
        num: Optional[int] = None,
        properties: Optional[list[str]] = None,
        schema_map: SchemaMapping = {},
        hydrate: bool = False,
        **kwargs,
    ) -> GeoDataFrame:
        """
        Read the data from the encoding.

        If `num` is specified, it will limit the number of rows read.
        If `properties` is specified, it will only read those properties.
        If `hydrate` is True, it will merge the collection metadata into the GeoDataFrame.
        """
        raise NotImplementedError("Not supported by encoding")

    def hydrate_from_collection(
        self, data: GeoDataFrame, schema_map: SchemaMapping = {}
    ) -> GeoDataFrame:
        """
        Merge the collection metadata into the GeoDataFrame.
        """
        collection = self.get_collection()
        collection_only = collection.get_collection_only_properties(schema_map=schema_map)
        keys = list(collection.keys())
        for key in keys:
            value = collection[key]
            if key in collection_only:
                continue
            if key not in data.columns:
                data[key] = value
                collection.pop(key, None)

        return data

    def dehydrate_to_collection(
        self,
        data: GeoDataFrame,
        properties: Optional[list[str]] = None,
        schema_map: SchemaMapping = {},
    ) -> GeoDataFrame:
        """
        Extract the collection metadata from the GeoDataFrame.

        This is all properties that are have the same value for all rows.
        Returns no values when only a single row is present.
        """
        collection = self.get_collection()
        if len(data) <= 1:
            return data

        context = collection.get_collection_context(schema_map=schema_map)
        columns = data.columns.copy()
        for key in columns:
            where = context.get(key, None)
            if where is not None:
                # Skip properties that should always be in the feature or collection
                continue
            if properties and key not in properties:
                continue

            # todo: This only works for scalar values, how to handle dicts, etc?
            try:
                if data[key].nunique(dropna=False) == 1:
                    collection[key] = data[key].iloc[0]
                    if key != "collection":
                        del data[key]
            except TypeError:
                pass

        return data
