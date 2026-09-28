import re
from typing import Optional

import pandas as pd
from geopandas import GeoDataFrame

from ..cli.logger import LoggerMixin
from ..encoding.base import BaseEncoding
from ..parquet.types import NULLABLE_INTEGERS, constant_array
from ..vecorel.collection import Collection
from ..vecorel.schemas import Schemas, VecorelSchema
from ..vecorel.typing import SchemaMapping


def report(message: str, log: Optional[LoggerMixin] = None, strict: bool = False):
    """
    A problem that makes the merged file invalid:
    an error in strict mode, otherwise a warning.
    """
    if strict:
        raise ValueError(message)
    if log:
        log.warning(message)


def merge(
    encodings: list[BaseEncoding],
    crs=None,
    properties=None,
    schema_map: SchemaMapping = {},
    log: Optional[LoggerMixin] = None,
    excludes: Optional[list[str]] = None,
    strict: bool = False,
) -> tuple[GeoDataFrame, Collection]:
    # before any data is read
    check_versions([item.get_collection() for item in encodings])
    frames = [item.read(properties=properties, schema_map=schema_map) for item in encodings]
    collections = [item.get_collection() for item in encodings]
    if excludes:
        if properties is None:
            properties = set()
            for gdf, collection in zip(frames, collections):
                properties |= set(gdf.columns) | set(collection.keys())
        properties = list(set(properties) - set(excludes))
        frames = [gdf.drop(columns=[c for c in excludes if c in gdf.columns]) for gdf in frames]
    merged_collection = merge_collections(
        collections, properties=properties, log=log, strict=strict, schema_map=schema_map
    )
    if properties is not None:
        warn_missing_required(collections, properties, schema_map, log, strict)
    props = merged_collection.merge_schemas(schema_map=schema_map).get("properties", {})

    data = []
    for item, gdf, collection in zip(encodings, frames, collections):
        # Only what the merged collection doesn't carry goes back into the rows
        keys = [
            key
            for key in collection
            if key not in merged_collection and (properties is None or key in properties)
        ]
        # Constants with a schema get their data type, as in DuckDB, e.g. binary is decoded;
        # a value that doesn't fit the data type would fail the writer, so it's left empty
        collection_only = set(collection.get_collection_only_properties(schema_map=schema_map))
        typed = {}
        for key in keys:
            if key in gdf.columns or key in collection_only or key not in collection:
                continue
            schema = props.get(key)
            try:
                array = constant_array(collection[key], schema, len(gdf))
            except ValueError as e:
                report(f"{key}: {e} (in {item.uri})", log, strict)
                array = constant_array(None, schema, len(gdf))
            if (schema or {}).get("type"):
                typed[key] = array
        gdf = item.hydrate_from_collection(gdf, schema_map=schema_map, keys=keys)
        for key, array in typed.items():
            series = array.to_pandas(types_mapper=NULLABLE_INTEGERS.get)
            series.index = gdf.index
            gdf[key] = series

        keep_collection = properties is None or "collection" in properties
        cid = get_collection_id(collection) if keep_collection else None
        if cid is not None and "collection" in gdf.columns:
            gdf["collection"] = gdf["collection"].fillna(cid)
        elif cid is not None:
            gdf["collection"] = cid
        elif keep_collection and (
            gdf["collection"].isna().any()
            if "collection" in gdf.columns
            else "collection" not in merged_collection
        ):
            report(f"Can't determine the collection of the features in {item.uri}", log, strict)

        if not crs:
            # If no CRS is given, use the first CRS that is available as the base CRS
            crs = gdf.crs
        else:
            # Change the CRS if necessary
            gdf.to_crs(crs=crs, inplace=True)

        data.append(gdf)

    # Concatenate all GeoDataFrames to a single GeoDataFrame
    merged = GeoDataFrame(pd.concat(data, ignore_index=True))
    # Remove empty columns, except for the geometry, which is required
    geometry = merged.geometry.name
    merged = merged.drop(
        columns=[c for c in merged.columns if c != geometry and merged[c].isna().all()]
    )

    if "id" in merged.columns:
        with_id = merged[merged["id"].notna()]
        key = [c for c in ("collection", "id") if c in merged.columns]
        duplicates = int(with_id.duplicated(subset=key).sum())
        if duplicates:
            report(f"{duplicates} rows repeat an id within their collection", log, strict)

    check_merged_data(merged, merged_collection, schema_map, log, strict, properties)

    return merged, merged_collection


def check_merged_data(
    merged: GeoDataFrame,
    collection: Collection,
    schema_map: SchemaMapping = {},
    log: Optional[LoggerMixin] = None,
    strict: bool = False,
    properties=None,
):
    """
    Reports empty geometries and missing required values, per collection.
    Properties that are not selected are reported by warn_missing_required.
    """
    geometries = merged.geometry
    empty = int((geometries.isna() | geometries.is_empty).sum())
    if empty:
        report(f"{empty} of {len(merged)} rows have an empty or missing geometry", log, strict)

    groups = collection.get_schemas()
    multiple = len(groups) > 1
    collection_only = set(collection.get_collection_only_properties(schema_map=schema_map))
    custom_schemas = collection.get_custom_schemas()
    missing = set()
    for cid, group in groups.items():
        if multiple:
            if "collection" not in merged.columns:
                continue
            rows = merged[merged["collection"] == cid]
        else:
            rows = merged
        if len(rows) == 0:
            continue
        schema = group.merge_schemas(schema_map=schema_map, custom_schemas=custom_schemas)
        for key in schema.get("required", []):
            if (
                key == "geometry"
                or key in collection_only
                or key in collection
                or (properties is not None and key not in properties)
            ):
                continue
            if key not in rows.columns or rows[key].isna().any():
                missing.add(key)
    if multiple and (properties is None or "collection" in properties):
        if "collection" not in merged.columns or merged["collection"].isna().any():
            missing.add("collection")
    if missing:
        report(
            f"Rows have no value for a required property: {', '.join(sorted(missing))}",
            log,
            strict,
        )


def get_collection_id(collection: Collection) -> Optional[str]:
    """
    The collection id of a dataset that doesn't state it for all features:
    the `collection` value in the collection metadata or the only collection in `schemas`.
    None if neither determines it.
    """
    cid = collection.get("collection")
    if isinstance(cid, str) and len(cid) > 0:
        return cid
    schemas = collection.get_schemas()
    if len(schemas) == 1:
        return next(iter(schemas.keys()))
    return None


def check_versions(collections: list[Collection]):
    """
    Fails if the datasets use different versions of the Vecorel specification or of an
    extension, in any of their collections, as they can't be upgraded automatically yet.
    """
    versions = {}
    for collection in collections:
        for uris in collection.get_schemas().values():
            for uri in uris:
                unversioned = re.sub(Schemas.version_pattern, "/", uri)
                if unversioned != uri:
                    versions.setdefault(unversioned, set()).add(uri)
    conflicts = ["; ".join(sorted(uris)) for uris in versions.values() if len(uris) > 1]
    if conflicts:
        raise ValueError(
            "The datasets use different versions of a schema, which can't be merged: "
            + " and ".join(sorted(conflicts))
        )


def warn_missing_required(
    collections: list[Collection],
    properties: list[str],
    schema_map: SchemaMapping,
    log: Optional[LoggerMixin] = None,
    strict: bool = False,
):
    """
    Reports required properties that the selected properties don't include.
    Checks the source collections, as the selection also drops the custom schemas
    that require a property.
    """
    missing = set()
    for collection in collections:
        schema = collection.merge_schemas(schema_map=schema_map)
        missing |= set(schema.get("required", [])) - set(properties)
    missing -= {"geometry", "schemas"}
    if missing:
        report(
            f"Required properties are not included, the merged file will be invalid: {', '.join(sorted(missing))}",
            log,
            strict,
        )


def merge_collections(
    collections: list[Collection],
    properties=None,
    log: Optional[LoggerMixin] = None,
    strict: bool = False,
    schema_map: SchemaMapping = {},
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

    if log or strict:
        # The other properties go back into the features, but collection-only properties can't
        dropped = set()
        required = set()
        for c in collections:
            keys = {
                k
                for k in c.keys()
                if k not in other_props
                and k not in handled_separately
                and (properties is None or k in properties)
            }
            if keys:
                dropped |= keys & set(c.get_collection_only_properties(schema_map=schema_map))
                required |= set(c.merge_schemas(schema_map=schema_map).get("required", []))
        message = "Collection-only properties differ between the datasets and are removed: "
        if dropped & required:
            report(message + ", ".join(sorted(dropped & required)), log, strict)
        if dropped - required and log:
            log.warning(message + ", ".join(sorted(dropped - required)))

    collection = Collection({"schemas": schemas, **other_props})
    collection.set_custom_schemas(custom_schemas)

    return collection
