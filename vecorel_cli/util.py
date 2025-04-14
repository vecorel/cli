import json
import os
import re
from pathlib import Path
from typing import Union
from urllib.parse import urlparse

import yaml
from fsspec import AbstractFileSystem
from fsspec.implementations.http import HTTPFileSystem
from fsspec.implementations.local import LocalFileSystem

file_cache = {}


# todo: remove
def log(text: str, status="info", nl=True):
    print(text)


def load_file(uri: Union[Path, str]) -> dict:
    """Load files from various sources"""
    if isinstance(uri, Path):
        uri = str(uri.absolute())
    if uri in file_cache:
        return file_cache[uri]

    fs = get_fs(uri)

    with fs.open(uri) as f:
        data = f.read()

    if uri.endswith(".yml") or uri.endswith(".yaml"):
        data = yaml.safe_load(data)
    elif uri.endswith(".json") or uri.endswith(".geojson"):
        data = json.loads(data)

    file_cache[uri] = data

    return data


def get_fs(url_or_path: str, **kwargs) -> AbstractFileSystem:
    """Choose fsspec filesystem by sniffing input url"""
    if isinstance(url_or_path, Path):
        url_or_path = str(url_or_path.absolute())
    parsed = urlparse(url_or_path)

    if parsed.scheme in ("http", "https"):
        return HTTPFileSystem(**kwargs)

    if parsed.scheme == "s3":
        from s3fs import S3FileSystem

        return S3FileSystem(**kwargs)

    if parsed.scheme == "gs":
        from gcsfs import GCSFileSystem

        return GCSFileSystem(**kwargs)

    return LocalFileSystem(**kwargs)


def filter_dict(obj: dict, keys) -> dict:
    """
    Filters the given dictionary to only include keys that are in the given keys.

    :param data: The dictionary to filter.
    :param keys: The set of keys to keep.
    :return: A new dictionary with only the keys that match the given keys.
    """
    return {k: v for k, v in obj.items() if k in keys}


def collection_from_featurecollection(geojson: dict) -> dict:
    """
    Extract collection data from a FeatureCollection

    :param geojson: The GeoJSON data to extract the collection from.
    :return: The collection data.
    """
    return filter_dict(geojson, ["type", "features"])


def name_from_uri(url):
    if "://" in url:
        try:
            url = urlparse(url).path
        except ValueError:
            pass
    return os.path.basename(url)


def is_schema_empty(schema):
    return len(schema.get("properties", {})) == 0 and len(schema.get("required", {})) == 0


def merge_schemas(*schemas):
    """Merge multiple schemas into one"""
    result = {"required": [], "properties": {}}
    for schema in schemas:
        schema = migrate_schema(schema)
        result["required"] += schema.get("required", [])
        result["properties"].update(schema.get("properties", {}))

    return result


def pick_schemas(schema, property_names, rename={}):
    """Pick and rename schemas for specific properties"""
    result = {"required": [], "properties": {}}
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    for prop in property_names:
        prop2 = rename[prop] if prop in rename else prop
        if prop in required:
            result["required"].append(prop2)
        if prop in properties:
            result["properties"][prop2] = properties[prop]

    return result


def migrate_schema(schema):
    """Migrate schema to a new version"""
    return schema.copy()


def to_iso8601(dt):
    iso = dt.isoformat()
    if iso.endswith("+00:00"):
        return iso[:-6] + "Z"
    elif re.search(r"[+-]\d{2}:\d{2}$", iso):
        raise ValueError("Timezone offset is not supported")
    else:
        return iso + "Z"


def format_filesize(size, decimal_places=2):
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if size < 1024.0 or unit == "PB":
            break
        size /= 1024.0
    return f"{size:.{decimal_places}f} {unit}"
