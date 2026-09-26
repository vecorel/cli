from typing import Optional

import pandas as pd
from geopandas import GeoDataFrame

from ..cli.logger import LoggerMixin
from ..encoding.base import BaseEncoding
from ..vecorel.collection import Collection
from ..vecorel.schemas import Schemas, VecorelSchema
from ..vecorel.typing import SchemaMapping


def merge(
    encodings: list[BaseEncoding],
    crs=None,
    properties=None,
    schema_map: SchemaMapping = {},
    log: Optional[LoggerMixin] = None,
) -> tuple[GeoDataFrame, Collection]:
    data = []
    collections = []

    for item in encodings:
        # Load the dataset
        gdf = item.read(hydrate=True, properties=properties, schema_map=schema_map)
        collection = item.get_collection()

        if "collection" not in gdf.columns or gdf["collection"].isna().any():
            cid = get_collection_id(collection, item.uri)
            if "collection" in gdf.columns:
                gdf["collection"] = gdf["collection"].fillna(cid)
            else:
                gdf["collection"] = cid

        if not crs:
            # If no CRS is given, use the first CRS that is available as the base CRS
            crs = gdf.crs
        else:
            # Change the CRS if necessary
            gdf.to_crs(crs=crs, inplace=True)

        # Add data to lists
        data.append(gdf)
        collections.append(collection)

    # Concatenate all GeoDataFrames to a single GeoDataFrame
    merged = GeoDataFrame(pd.concat(data, ignore_index=True))
    # Remove empty columns
    merged.dropna(axis=1, how="all", inplace=True)

    if log and "id" in merged.columns:
        with_id = merged[merged["id"].notna()]
        duplicates = int(with_id.duplicated(subset=["collection", "id"]).sum())
        if duplicates:
            log.warning(f"{duplicates} rows repeat an id within their collection")

    # Merge all collections
    collection = merge_collections(collections, properties=properties, log=log)
    if log and properties is not None:
        warn_missing_required(collection, properties, schema_map, log)

    return merged, collection


def get_collection_id(collection: Collection, source=None) -> str:
    """
    The collection id of a dataset that doesn't state it for all features:
    the `collection` value in the collection metadata or the only collection in `schemas`.
    """
    cid = collection.get("collection")
    if isinstance(cid, str) and len(cid) > 0:
        return cid
    schemas = collection.get_schemas()
    if len(schemas) == 1:
        return next(iter(schemas.keys()))
    raise ValueError(f"Can't determine the collection of the features in {source}")


def warn_missing_required(
    collection: Collection, properties: list[str], schema_map: SchemaMapping, log: LoggerMixin
):
    schema = collection.merge_schemas(schema_map=schema_map)
    collection_only = set(collection.get_collection_only_properties(schema_map=schema_map))
    missing = set(schema.get("required", [])) - set(properties) - collection_only - {"geometry"}
    if missing:
        log.warning(
            f"Required properties are not included, the merged file will be invalid: {', '.join(sorted(missing))}"
        )


def merge_collections(
    collections: list[Collection], properties=None, log: Optional[LoggerMixin] = None
) -> Collection:
    schemas = Schemas()
    custom_schemas = VecorelSchema()
    handled_separately = ("schemas", "schemas:custom")

    # Additional collection metadata (e.g. collection-only properties) is kept
    # if it's present in all collections with the same value, i.e. it still
    # applies to the merged dataset as a whole.
    other_props = None
    for collection in collections:
        schemas.add_all(collection.get_schemas())

        custom = collection.get_custom_schemas()
        custom_schemas.merge(custom)

        props = {k: v for k, v in collection.items() if k not in handled_separately}
        if other_props is None:
            other_props = props
        else:
            other_props = {k: v for k, v in other_props.items() if k in props and props[k] == v}

    if other_props is None:
        other_props = {}
    if properties is not None:
        other_props = {k: v for k, v in other_props.items() if k in properties}
        custom_schemas = custom_schemas.pick(properties)

    if log:
        # The other properties go back into the features, but collection-only properties can't
        dropped = set()
        for c in collections:
            keys = {
                k
                for k in c.keys()
                if k not in other_props
                and k not in handled_separately
                and (properties is None or k in properties)
            }
            if keys:
                dropped |= keys & set(c.get_collection_only_properties())
        if dropped:
            log.warning(
                "Collection-only properties differ between the datasets and are removed: "
                + ", ".join(sorted(dropped))
            )

    collection = Collection({"schemas": schemas, **other_props})
    collection.set_custom_schemas(custom_schemas)

    return collection
