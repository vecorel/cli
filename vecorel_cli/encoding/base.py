from pathlib import Path
from typing import Optional, Union

from geopandas import GeoDataFrame

from ..cli.logger import LoggerMixin
from ..vecorel.schemas import Schemas
from ..vecorel.util import format_filesize


NON_COLLECTION_PROPERTIES = ["id", "geometry", "bbox", "schemas"]


class BaseEncoding(LoggerMixin):
    ext = []

    def __init__(self, file: Union[Path, str]):
        self.file = Path(file)

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

    def get_collection(self) -> dict:
        return {}

    def get_properties(self) -> Optional[dict[str, str]]:
        return None

    def get_metadata(self) -> dict:
        return {}

    def write(
        self,
        data: GeoDataFrame,
        collection: dict = {},
        properties: Optional[list[str]] = None,
        schema_map: dict = {},
        missing_schemas: dict = {},
        hydrate: bool = False,
        **kwargs,
    ) -> bool:
        raise NotImplementedError("Subclasses must implement this method")

    def read(
        self, num: Optional[int] = None, properties: Optional[list[str]] = None, hydrate: bool = False, **kwargs
    ) -> GeoDataFrame:
        raise NotImplementedError("Not supported by encoding")

    def hydrate_from_collection(self, data: GeoDataFrame, collection: dict) -> GeoDataFrame:
        """
        Merge the collection metadata into the GeoDataFrame.
        """
        for key, value in collection.items():
            if key in NON_COLLECTION_PROPERTIES:
                continue
            if key not in data.columns:
                data[key] = value

        return data

    def hydrate_to_collection(self, data: GeoDataFrame) -> dict:
        """
        Extract the collection metadata from the GeoDataFrame.

        This is all properties that are have the same value for all rows.
        Returns no values when only a single row is present.
        """
        collection = self.get_collection()
        if len(data) <= 1:
            return collection

        for key in data.columns:
            if key in NON_COLLECTION_PROPERTIES:
                continue
            if data[key].nunique() == 1:
                collection[key] = data[key].iloc[0]
                if key != "collection":
                    del data[key]

        self.collection = collection
        return self.collection
