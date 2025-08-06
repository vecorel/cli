from pathlib import Path
from typing import Optional, Union

from geopandas import GeoDataFrame

from ..cli.logger import LoggerMixin
from ..validation.base import Validator
from ..vecorel.collection import Collection
from ..vecorel.typing import SchemaMapping
from ..vecorel.util import format_filesize


class BaseEncoding(LoggerMixin):
    ext = []
    non_collection_properties = ["id", "geometry", "bbox", "schemas", "schemas:custom"]

    def __init__(self, file: Union[Path, str]):
        self.file = Path(file)
        self.collection: Optional[Collection] = None

    def get_format(self) -> str:
        return "unknown"

    def get_summary(self) -> dict:
        """
        Summarize key statistics quickly for human consumption.
        """
        return {
            "Format": self.get_format(),
            "Size": format_filesize(self.file.stat().st_size),
            "Compression": self.get_compression() or "None",
        }

    def _load_collection(self) -> dict:
        return {}

    def get_collection(self) -> Collection:
        """
        Get the collection metadata.
        """
        if self.collection is None:
            if self.file.exists():
                self.collection = Collection(self._load_collection())
            else:
                self.collection = Collection()
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

    def hydrate_from_collection(self, data: GeoDataFrame) -> GeoDataFrame:
        """
        Merge the collection metadata into the GeoDataFrame.
        """
        collection = self.get_collection()
        keys = list(collection.keys())
        for key in keys:
            value = collection[key]
            if key in BaseEncoding.non_collection_properties:
                continue
            if key not in data.columns:
                data[key] = value
                del collection[key]

        return data

    def dehydrate_to_collection(
        self, data: GeoDataFrame, properties: Optional[list[str]] = None
    ) -> GeoDataFrame:
        """
        Extract the collection metadata from the GeoDataFrame.

        This is all properties that are have the same value for all rows.
        Returns no values when only a single row is present.
        """
        collection = self.get_collection()
        if len(data) <= 1:
            return data

        for key in data.columns:
            if key in BaseEncoding.non_collection_properties:
                continue
            if properties and key not in properties:
                continue

            if data[key].nunique(dropna=False) == 1:
                collection[key] = data[key].iloc[0]
                if key != "collection":
                    del data[key]

        return data
