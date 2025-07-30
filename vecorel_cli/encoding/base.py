from pathlib import Path
from typing import Optional, Union

from geopandas import GeoDataFrame

from ..cli.logger import LoggerMixin
from ..vecorel.schemas import Schemas
from ..vecorel.typing import Collection
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
        }

    def get_schemas(self) -> dict[str, Schemas]:
        collection = self.get_collection()
        schemas = collection.get("schemas", {})
        for key, value in schemas.items():
            schemas[key] = Schemas(value, key)
        return schemas

    def get_collection_schemas(self, collection: str) -> Schemas:
        collections = self.get_all_schemas()
        return collections.get(collection, Schemas())

    def get_custom_schemas(self) -> dict[str, dict]:
        """
        Get custom schemas from the collection.
        """
        collection = self.get_collection()
        return collection.get("schemas:custom", {})

    def set_custom_schemas(self, custom_schemas: dict[str, dict]):
        """
        Set custom schemas in the collection.
        """
        collection = self.get_collection()
        collection["schemas:custom"] = custom_schemas
        self.collection = collection

    def get_collection(self) -> Collection:
        """
        Get the collection metadata.
        """
        return self.collection or {}

    def set_collection(self, collection: Collection):
        self.collection = collection

    def get_properties(self) -> Optional[dict[str, list[str]]]:
        return None

    def get_metadata(self) -> dict:
        return {}

    def write(
        self,
        data: GeoDataFrame,
        properties: Optional[list[str]] = None,
        schema_map: dict = {},
        missing_schemas: dict = {},
        dehydrate: bool = True,
        **kwargs,
    ) -> bool:
        raise NotImplementedError("Subclasses must implement this method")

    def read(
        self,
        num: Optional[int] = None,
        properties: Optional[list[str]] = None,
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

        self.collection = collection
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
            if data[key].nunique() == 1:
                collection[key] = data[key].iloc[0]
                if key != "collection":
                    del data[key]

        self.collection = collection
        return data
