import json
from pathlib import Path
from typing import Optional, Union

import json_stream
import numpy as np
import pandas as pd
from geopandas import GeoDataFrame
from pandas import DataFrame
from shapely.geometry import shape

from ..vecorel.util import load_file, to_iso8601
from .base import BaseEncoding


class GeoJSON(BaseEncoding):
    datatypes_schema_uri = "https://fiboa.github.io/specification/v{version}/geojson/datatypes.json"
    ext = [".json", ".geojson"]
    crs = "EPSG:4326"

    def __init__(self, file: str):
        super().__init__(file)
        self.collection = None

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

    def get_collection(self) -> dict:
        if self.collection is None:
            self.read(num=0)
        return self.collection or {}

    # todo: we shouldn't use iterfeature / __geo_interface__ directly
    # it doesn't correctly coverts some data types which are present in the Vecorel SDL
    # e.g. lists of tuples into a dict

    # kwargs:
    #   indent: int, optional, default None
    #       If set, the JSON will be pretty-printed with the given indentation level.
    def write(
        self,
        data: GeoDataFrame,
        collection: dict = {},
        properties: Optional[list[str]] = None,
        schema_map: dict = {},
        missing_schemas: dict = {},
        **kwargs,
    ) -> bool:
        indent = kwargs.get("indent", None)

        self.file.parent.mkdir(parents=True, exist_ok=True)

        # We need to write GeoJSON in EPSG:4326
        data = data.to_crs(epsg=4326)

        # Convert to GeoJSON
        obj = data.__geo_interface__

        # Remove bbox from the GeoJSON object
        del obj["bbox"]

        # Make Python's GeoJSON variant valid and compliant with Vecorel GeoJSON
        obj["features"] = list(map(self._fix_geojson, obj["features"]))

        # Add collection metadata to the FeatureCollection top-level properties
        if isinstance(collection, dict):
            obj.update(collection)

        self._write_json(obj, self.file, indent=indent)

    def write_as_features(
        self,
        data: GeoDataFrame,
        folder: Union[Path, str],
        collection: dict = {},
        properties: Optional[list[str]] = None,
        schema_map: dict = {},
        **kwargs,
    ) -> bool:
        if isinstance(folder, str):
            folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)

        i = 1
        for obj in data.iterfeatures():
            if (i % 1000) == 0:
                self.log(f"{i}...", nl=(i % 10000) == 0)

            if isinstance(collection, dict):
                obj["properties"].update(collection)

            obj = self._fix_geojson(obj)

            id = obj.get("id", i)
            path = folder.joinpath(f"{id}.json")
            self.write_json(obj, path, indent=kwargs.get("indent", None))

            i += 1

    def read(
        self, num: Optional[int] = None, properties: Optional[list[str]] = None, **kwargs
    ) -> GeoDataFrame:
        # note: To read a GeoJSON Feature num and properties must be set to None
        if num is None and properties is None:
            # The memory intensive way: read the whole file into memory
            gdf, collection = self._read_json()
        else:
            # The memory efficient way: stream the file
            gdf, collection = self._stream_json()

        self.collection = collection
        return gdf

    def _read_json(
        self, num: Optional[int] = None, properties: Optional[list[str]] = None, **kwargs
    ) -> GeoDataFrame:
        with open(self.file, "r", **kwargs) as f:
            obj = json.load(f)

        if not isinstance(obj, dict):
            raise ValueError("JSON file must contain a GeoJSON object")
        if obj["type"] == "Feature":
            obj = {"type": "FeatureCollection", "features": [obj]}
        if obj["type"] != "FeatureCollection":
            raise ValueError("JSON file must contain a FeatureCollection")

        # Preserve id: https://github.com/geopandas/geopandas/issues/1208
        for feature in obj["features"]:
            if "id" not in feature["properties"]:
                feature["properties"]["id"] = feature["id"]

        collection = {}
        # Add non-GeoJSON properties to the collection metadata
        for key, value in obj.items():
            if key == "type" or key == "features":
                continue
            else:
                collection[key] = value

        gdf = GeoDataFrame.from_features(obj, crs=self.crs, columns=properties)
        return gdf, collection

    def _stream_json(
        self, num: Optional[int] = None, properties: Optional[list[str]] = None, **kwargs
    ) -> GeoDataFrame:
        with open(self.file, "r", **kwargs) as f:
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
                        return self._read_json(**kwargs)
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

    def _fix_geojson(self, obj):
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
        obj["properties"] = self._fix_omit_nulled_properties(obj["properties"])

        return obj

    def _fix_omit_nulled_properties(self, obj):
        for key in obj.keys():
            if obj[key] is None:
                del obj[key]
            elif isinstance(obj[key], dict):
                obj[key] = self._fix_omit_nulled_properties(obj[key])
            elif isinstance(obj[key], list):
                for i, item in enumerate(obj[key]):
                    if not isinstance(item, dict):
                        continue
                    obj[key][i] = self._fix_omit_nulled_properties(item)

        return obj


class VecorelJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, pd.Timestamp):
            return to_iso8601(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        else:
            return super().default(obj)
