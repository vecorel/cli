import pandas as pd
from geopandas import GeoDataFrame

from ..encoding.base import BaseEncoding
from ..vecorel.collection import Collection
from ..vecorel.schemas import Schemas, VecorelSchema
from ..vecorel.typing import SchemaMapping


def merge(
    encodings: list[BaseEncoding],
    crs=None,
    properties=None,
    schema_map: SchemaMapping = {},
) -> tuple[GeoDataFrame, Collection]:
    data = []
    collections = []

    for item in encodings:
        # Load the dataset
        gdf = item.read(hydrate=True, properties=properties, schema_map=schema_map)

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
    schemas = Schemas()
    custom_schemas = VecorelSchema()

    for collection in collections:
        schemas.add_all(collection.get_schemas())

        custom = collection.get_custom_schemas()
        custom_schemas.merge(custom)

    collection = Collection(
        {
            "schemas": schemas,
        }
    )

    if properties is not None:
        custom_schemas = custom_schemas.pick(properties)

    collection.set_custom_schemas(custom_schemas)

    return collection
