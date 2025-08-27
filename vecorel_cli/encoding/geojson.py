import json
from pathlib import Path
from typing import Optional, Union

import json_stream
import numpy as np
import pandas as pd
from geopandas import GeoDataFrame
from pandas import DataFrame
from shapely.geometry import shape
from yarl import URL

from ..validation.base import Validator
from ..vecorel.collection import Collection
from ..vecorel.typing import Feature, FeatureCollection, SchemaMapping
from ..vecorel.util import load_file, to_iso8601
from .base import BaseEncoding


class GeoJSON(BaseEncoding):
    feature_properties = {"type", "id", "geometry", "bbox", "properties"}
    feature_collection_properties = {"type", "features"}
    datatypes_schema_uri = "https://vecorel.org/specification/v{version}/geojson/datatypes.json"
    ext = [".json", ".geojson"]
    media_type = "application/geo+json"
    crs = "EPSG:4326"

    def __init__(self, file: Union[Path, URL, str]):
        super().__init__(file)

    @staticmethod
    def load_datatypes(uri: Union[Path, URL, str]) -> dict:
        response = load_file(uri)
        return response.get("$defs", {})

    @staticmethod
    def get_datatypes_uri(version: str) -> str:
        return GeoJSON.datatypes_schema_uri.format(version=version)

    def get_format(self) -> str:
        return "GeoJSON"

    def _load_collection(self) -> dict:
        if self.fs.exists(self.uri):
            self.read(num=0)
        return self.collection

    def get_validator(self) -> Optional[Validator]:
        from ..validation.geojson import GeoJSONValidator

        return GeoJSONValidator(self)

    # todo: we shouldn't use iterfeature / __geo_interface__ directly
    # it doesn't correctly coverts some data types which are present in the Vecorel SDL
    # e.g. lists of tuples into a dict

    # indent: int, optional, default None
    #     If set, the JSON will be pretty-printed with the given indentation level.
    def write(
        self,
        data: GeoDataFrame,
        properties: Optional[list[str]] = None,
        schema_map: SchemaMapping = {},
        dehydrate: bool = True,
        indent: Optional[int] = None,
        **kwargs,  # capture unknown arguments
    ) -> bool:
        self.uri.parent.mkdir(parents=True, exist_ok=True)

        if dehydrate:
            data = self.dehydrate_to_collection(data, properties=properties, schema_map=schema_map)

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

        self._write_json(collection, self.uri, indent=indent)

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
        self.uri.parent.mkdir(parents=True, exist_ok=True)

        # If the input is originating from a __geo_interface__ object,
        # it may not be in the correct format.
        data = GeoJSON.fix_geo_interface(data)

        # Let's get all collection metadata into the feature itself
        collection = self.get_collection()
        collection_only = collection.get_collection_only_properties()
        for key, value in collection.items():
            if key not in collection_only:
                data["properties"][key] = value
            elif key not in GeoJSON.feature_properties:
                data[key] = value

        # Remove properties that are not in the properties list
        for key, value in data["properties"].items():
            if properties is not None and key not in properties:
                data["properties"].pop(key)

        self._write_json(data, self.uri, indent=indent)

    def read(
        self,
        num: Optional[int] = None,
        properties: Optional[list[str]] = None,
        schema_map: SchemaMapping = {},
        hydrate: bool = False,
    ) -> GeoDataFrame:
        if num is None and properties is None:
            # The memory intensive and fast way: read the whole file into memory
            gdf = self._read_json(num=num, properties=properties, schema_map=schema_map)
        else:
            # The memory efficient way: stream the file
            gdf = self._stream_json(num=num, properties=properties, schema_map=schema_map)

        if hydrate:
            gdf = self.hydrate_from_collection(gdf, schema_map=schema_map)

        return gdf

    def read_geojson(
        self,
        num: Optional[int] = None,
        schema_map: SchemaMapping = {},
        hydrate: bool = False,
        enforce_featurecollection: bool = False,
    ) -> Union[FeatureCollection, Feature]:
        # num only applies to FeatureCollections
        with open(self.uri, "r") as f:
            obj = json.load(f)

        if not isinstance(obj, dict):
            raise ValueError("JSON file must contain a GeoJSON object")
        if obj["type"] != "FeatureCollection" and obj["type"] != "Feature":
            raise ValueError("JSON file must contain a FeatureCollection or Feature")

        is_feature = obj["type"] == "Feature"

        # Extract collection metadata (i.e. non-GeoJSON properties) from the GeoJSON object.
        collection = Collection()
        geojson_props = (
            GeoJSON.feature_properties if is_feature else GeoJSON.feature_collection_properties
        )
        for key, value in obj.items():
            if key not in geojson_props:
                collection[key] = value

        # Wrap a single Feature into a FeatureCollection
        if is_feature and enforce_featurecollection:
            obj = {"type": "FeatureCollection", "features": [obj]}

        # Restrict to number of features requested
        if not is_feature and num is not None:
            obj["features"] = obj["features"][:num]

        # Move the collection properties to the Features in the FeatureCollection.
        # Not needed for Features according to the specification.
        if hydrate and not is_feature:
            obj, collection = self._hydrate_featurecollection(
                obj, collection, schema_map=schema_map
            )

        self.set_collection(collection)

        return obj

    def _hydrate_featurecollection(
        self, data: FeatureCollection, collection: Collection, schema_map: SchemaMapping = {}
    ) -> tuple[FeatureCollection, Collection]:
        collection_only = collection.get_collection_only_properties(schema_map=schema_map)

        # Split the collection metadata into two parts:
        # 1. Properties that should be added to each Feature
        # 2. Properties that should remain in the collection metadata
        merge_to_features = Collection()
        new_collection = Collection()
        for key, value in collection.items():
            c = new_collection if key in collection_only else merge_to_features
            c[key] = value

        # Add the remaining collection metadata to each feature
        for feature in data["features"]:
            feature.update(merge_to_features)

        return data, new_collection

    def _read_json(
        self,
        num: Optional[int] = None,
        schema_map: SchemaMapping = {},
        properties: Optional[list[str]] = None,
    ) -> GeoDataFrame:
        obj = self.read_geojson(num=num, schema_map=schema_map, enforce_featurecollection=True)

        # Preserve id: https://github.com/geopandas/geopandas/issues/1208
        for feature in obj["features"]:
            if "id" not in feature["properties"]:
                feature["properties"]["id"] = feature["id"]

        crs = self.crs if len(obj["features"]) > 0 else None
        gdf = GeoDataFrame.from_features(obj, crs=crs, columns=properties)
        return gdf

    def _stream_json(
        self,
        num: Optional[int] = None,
        schema_map: SchemaMapping = {},
        properties: Optional[list[str]] = None,
    ) -> GeoDataFrame:
        with open(self.uri, "r") as f:
            stream = json_stream.load(f)
            data = {
                "id": [],
                "geometry": [],
            }
            self.collection = Collection()

            for key, value in stream.items():
                if key == "type":
                    if value == "Feature":
                        # The memory efficient way can't easily read individual Features
                        # use the other method
                        return self._read_json(
                            num=num, properties=properties, schema_map=schema_map
                        )
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
                    self.collection[key] = json_stream.to_standard_types(value)

            gdf = GeoDataFrame(DataFrame.from_dict(data), crs=self.crs, geometry="geometry")
            return gdf

    def _write_json(self, obj, path, indent=None):
        with open(path, "w") as f:
            json.dump(obj, f, allow_nan=False, indent=indent, cls=VecorelJSONEncoder)

    @staticmethod
    def fix_geo_interface(obj):
        # Fix id
        if "id" in obj["properties"]:
            obj["id"] = obj["properties"]["id"]
            obj["properties"].pop("id")

        # Fix bbox
        if (
            "bbox" not in obj
            and "bbox" in obj["properties"]
            and isinstance(obj["properties"]["bbox"], dict)
        ):
            bbox = obj["properties"]["bbox"]
            obj["bbox"] = [bbox["xmin"], bbox["ymin"], bbox["xmax"], bbox["ymax"]]
            obj["properties"].pop("bbox")

        # Remove null values
        obj["properties"] = GeoJSON._fix_omit_nulled_properties(obj["properties"])

        return obj

    @staticmethod
    def _fix_omit_nulled_properties(obj):
        for key in obj.keys():
            if obj[key] is None:
                obj.pop(key)
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
        elif isinstance(obj, set):
            return list(obj)
        elif isinstance(obj, np.generic):
            return obj.item()
        else:
            return super().default(obj)
