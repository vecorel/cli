import pandas as pd
from geopandas import GeoDataFrame

from ..encoding.base import BaseEncoding
from ..jsonschema.util import (
    is_schema_empty,
    merge_schemas,
    pick_schemas,
)
from ..vecorel.typing import Collection


def merge(
    encodings: list[BaseEncoding],
    crs=None,
    properties=None,
) -> tuple[GeoDataFrame, Collection]:
    data = []
    collections = []

    for item in encodings:
        # Load the dataset
        gdf = item.read(hydrate=True, properties=properties)

        if not crs:
            # If no CRS is given, use the first CRS that is available as the base CRS
            crs = gdf.crs
        else:
            # Change the CRS if necessary
            gdf.to_crs(crs=crs, inplace=True)

        # Add data to lists
        data.append(gdf)
        collections.append(item.get_collection())

    # Concatenate all GeoDataFrames to a single GeoDataFrame
    merged = pd.concat(data, ignore_index=True)
    # Remove empty columns
    merged.dropna(axis=1, how="all", inplace=True)

    # Merge all collections
    collection = merge_collections(collections, properties=properties)

    return merged, collection


def merge_collections(collections: list[Collection], properties=None) -> Collection:
    schemas = {}
    custom_schemas = {}

    for collection in collections:
        schemas.update(collection.get("schemas", {}))

        custom = collection.get("schemas:custom", {})
        if not is_schema_empty(custom):
            custom_schemas = merge_schemas(custom_schemas, custom)

    collection = {
        "schemas": schemas,
    }

    if properties is not None:
        custom_schemas = pick_schemas(custom_schemas, properties)
    if not is_schema_empty(custom_schemas):
        collection["schemas:custom"] = custom_schemas

    return collection
