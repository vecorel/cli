from pathlib import Path
from typing import Optional, Union

from geopandas import GeoDataFrame

from ..util import format_filesize
from ..vecorel.schemas import Schemas


class BaseEncoding:
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

    def get_columns(self) -> Optional[dict[str, str]]:
        return None

    def get_metadata(self) -> dict:
        return {}

    def write(self, data: GeoDataFrame, collection: dict = {}, **kwargs) -> bool:
        raise NotImplementedError("Subclasses must implement this method")

    def read(self, num: int = None, columns: list[str] = None, **kwargs) -> GeoDataFrame:
        raise NotImplementedError("Not supported by encoding")
