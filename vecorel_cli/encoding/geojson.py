import json
from pathlib import Path
from typing import Optional, Union

import json_stream
import numpy as np
import pandas as pd
from geopandas import GeoDataFrame
from pandas import DataFrame
from shapely.geometry import shape

from ..vecorel.typing import Collection
from ..vecorel.util import load_file, to_iso8601
from .base import BaseEncoding

FEATURE_PROPS = ["type", "id", "geometry", "bbox", "properties"]
FEATURE_COLLECTION_PROPS = ["type", "features"]


class GeoJSON(BaseEncoding):
    datatypes_schema_uri = "https://fiboa.github.io/specification/v{version}/geojson/datatypes.json"
    ext = [".json", ".geojson"]
    crs = "EPSG:4326"

    def __init__(self, file: Union[Path, str]):
        super().__init__(file)

    @staticmethod
    def load_datatypes(uri: str) -> dict:
        response = load_file(uri)
        return response.get("$defs", {})

    @staticmethod
    def get_datatypes_uri(version: str) -> str:
        return GeoJSON.datatypes_schema_uri.format(version=version)

    def get_datatypes(self) -> dict:
        version = self.get_version()
        if version is None:
            return {}
        return self.load_datatypes(version)

    def get_format(self) -> str:
        return "GeoJSON"

    def get_collection(self) -> Collection:
        if self.collection is None and self.file.exists():
            self.read(num=0)
        return super().get_collection()

    # todo: we shouldn't use iterfeature / __geo_interface__ directly
    # it doesn't correctly coverts some data types which are present in the Vecorel SDL
    # e.g. lists of tuples into a dict

    # indent: int, optional, default None
    #     If set, the JSON will be pretty-printed with the given indentation level.
    def write(
        self,
        data: GeoDataFrame,
        properties: Optional[list[str]] = None,
        schema_map: dict = {},
        missing_schemas: dict = {},
        dehydrate: bool = True,
        indent: Optional[int] = None,
    ) -> bool:
        self.file.parent.mkdir(parents=True, exist_ok=True)

        if dehydrate:
            data = self.dehydrate_to_collection(data, properties=properties)

        # We need to write GeoJSON in EPSG:4326
        data.to_crs(epsg=4326, inplace=True)

        # Convert to GeoJSON
        features = data.__geo_interface__["features"]

        # Make Python's GeoJSON variant valid and compliant with Vecorel GeoJSON
        features = list(map(GeoJSON.fix_geo_interface, features))

        # Add collection metadata to the FeatureCollection top-level properties
        collection = self.get_collection()
        collection["type"] = "FeatureCollection"
        collection["features"] = features

        self._write_json(collection, self.file, indent=indent)

    # indent: int, optional, default None
    #     If set, the JSON will be pretty-printed with the given indentation level.
    def write_feature(
        self,
        data: dict,
        properties: Optional[list[str]] = None,
        indent: Optional[int] = None,
    ) -> bool:
        """
        Write a single GeoJSON feature to the file.

        The dict must be reprojected to EPSG:4326.
        """
        self.file.parent.mkdir(parents=True, exist_ok=True)

        # If the input is originating from a __geo_interface__ object,
        # it may not be in the correct format.
        data = GeoJSON.fix_geo_interface(data.copy())

        # Let's get all collection metadata into the feature itself
        collection = self.get_collection()
        for key, value in collection.items():
            if key not in BaseEncoding.non_collection_properties:
                data["properties"][key] = value
            elif key not in FEATURE_PROPS:
                data[key] = value

        # Remove properties that are not in the properties list
        for key, value in data["properties"].items():
            if properties is not None and key not in properties:
                del data["properties"][key]

        self._write_json(data, self.file, indent=indent)

    def read(
        self,
        num: Optional[int] = None,
        properties: Optional[list[str]] = None,
        hydrate: bool = False,
    ) -> GeoDataFrame:
        # note: To read a GeoJSON Feature num and properties must be set to None
        if num is None and properties is None:
            # The memory intensive way: read the whole file into memory
            # todo: Should we remove this and always use the streaming method?
            gdf, collection = self._read_json(num=num, properties=properties)
        else:
            # The memory efficient way: stream the file
            gdf, collection = self._stream_json(num=num, properties=properties)

        self.collection = collection

        if hydrate:
            gdf = self.hydrate_from_collection(gdf)

        return gdf

    def _collection_from_geojson(self, geojson: dict) -> Collection:
        """
        Extract collection metadata (i.e. non-GeoJSON properties) from the GeoJSON object.
        """
        core_props = FEATURE_PROPS if geojson["type"] == "Feature" else FEATURE_COLLECTION_PROPS
        collection = {}
        for key, value in geojson.items():
            if key in core_props:
                continue
            else:
                collection[key] = value
        return collection

    def _read_json(
        self, num: Optional[int] = None, properties: Optional[list[str]] = None
    ) -> tuple[GeoDataFrame, Collection]:
        with open(self.file, "r") as f:
            obj = json.load(f)

        if not isinstance(obj, dict):
            raise ValueError("JSON file must contain a GeoJSON object")
        if obj["type"] != "FeatureCollection" and obj["type"] != "Feature":
            raise ValueError("JSON file must contain a FeatureCollection or Feature")

        collection = self._collection_from_geojson(obj)

        if obj["type"] == "Feature":
            obj = {"type": "FeatureCollection", "features": [obj]}

        # Preserve id: https://github.com/geopandas/geopandas/issues/1208
        for feature in obj["features"]:
            if "id" not in feature["properties"]:
                feature["properties"]["id"] = feature["id"]

        gdf = GeoDataFrame.from_features(obj, crs=self.crs, columns=properties)
        if num is not None:
            gdf = gdf.head(num)
        return gdf, collection

    def _stream_json(
        self, num: Optional[int] = None, properties: Optional[list[str]] = None
    ) -> tuple[GeoDataFrame, Collection]:
        with open(self.file, "r") as f:
            stream = json_stream.load(f)
            data = {
                "id": [],
                "geometry": [],
            }
            collection = {}

            for key, value in stream.items():
                if key == "type":
                    if value == "Feature":
                        # The memory efficient way can't easily read individual Features
                        # so we use _read_json() instead
                        return self._read_json(num=num, properties=properties)
                    elif value != "FeatureCollection":
                        raise ValueError("JSON file must contain a FeatureCollection")
                    else:
                        continue
                elif key == "features":
                    i = 0
                    for feature in value:
                        for k, v in feature.items():
                            include = properties is None or k in properties
                            if k == "id" and include:
                                data["id"].append(json_stream.to_standard_types(v))
                            elif k == "geometry" and include:
                                geom = shape(json_stream.to_standard_types(v))
                                data["geometry"].append(geom)
                            elif k == "properties":
                                for prop_key, prop_value in v.items():
                                    # Property is not relevant
                                    if properties is not None and prop_key not in properties:
                                        continue
                                    # New property, prepend None values if this is not the first feature
                                    if prop_key not in data:
                                        data[prop_key] = [None] * i
                                    # Append the value
                                    data[prop_key].append(json_stream.to_standard_types(prop_value))

                        # If a property was not found in the feature, add None to the array of the column
                        for key in data.keys():
                            if len(data[key]) == i:
                                data[key].append(None)

                        i = i + 1
                        # If a limit is set, break the loop
                        if num is not None and i >= num:
                            break
                else:
                    # Add non-GeoJSON properties to the collection metadata
                    collection[key] = json_stream.to_standard_types(value)

            gdf = GeoDataFrame(DataFrame.from_dict(data), crs=self.crs, geometry="geometry")
            return gdf, collection

    def _write_json(self, obj, path, indent=None):
        with open(path, "w") as f:
            json.dump(obj, f, allow_nan=False, indent=indent, cls=VecorelJSONEncoder)

    @staticmethod
    def fix_geo_interface(obj):
        # Fix id
        if "id" in obj["properties"]:
            obj["id"] = obj["properties"]["id"]
            del obj["properties"]["id"]

        # Fix bbox
        if (
            "bbox" not in obj
            and "bbox" in obj["properties"]
            and isinstance(obj["properties"]["bbox"], dict)
        ):
            bbox = obj["properties"]["bbox"]
            obj["bbox"] = [bbox["xmin"], bbox["ymin"], bbox["xmax"], bbox["ymax"]]
            del obj["properties"]["bbox"]

        # Remove null values
        obj["properties"] = GeoJSON._fix_omit_nulled_properties(obj["properties"])

        return obj

    @staticmethod
    def _fix_omit_nulled_properties(obj):
        for key in obj.keys():
            if obj[key] is None:
                del obj[key]
            elif isinstance(obj[key], dict):
                obj[key] = GeoJSON._fix_omit_nulled_properties(obj[key])
            elif isinstance(obj[key], list):
                for i, item in enumerate(obj[key]):
                    if not isinstance(item, dict):
                        continue
                    obj[key][i] = GeoJSON._fix_omit_nulled_properties(item)

        return obj


class VecorelJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, pd.Timestamp):
            return to_iso8601(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        else:
            return super().default(obj)
