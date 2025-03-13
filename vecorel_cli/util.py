import json
import os
import re
from pathlib import Path
from typing import Union
from urllib.parse import urlparse

import click
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml
from fsspec import AbstractFileSystem
from fsspec.implementations.http import HTTPFileSystem
from fsspec.implementations.local import LocalFileSystem
from geopandas.io.arrow import _arrow_to_geopandas
from pyarrow import NativeFile
from pyarrow.fs import FSSpecHandler, PyFileSystem

from .const import (
    GEOPARQUET_SCHEMA,
    SUPPORTED_PROTOCOLS,
    VECOREL_SPECIFICAION_PATTERN,
)

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


def get_pyarrow_file(uri) -> NativeFile:
    fs = get_fs(uri)
    pyarrow_fs = PyFileSystem(FSSpecHandler(fs))
    return pyarrow_fs.open_input_file(uri)


def load_parquet_schema(uri: Union[str, NativeFile]) -> pq.ParquetSchema:
    """Load schema from Parquet file"""
    if isinstance(uri, str):
        uri = get_pyarrow_file(uri)
    return pq.read_schema(uri)


def load_parquet_metadata(uri: Union[str, NativeFile]) -> pq.FileMetaData:
    """Load metadata from Parquet file"""
    if isinstance(uri, str):
        uri = get_pyarrow_file(uri)
    return pq.read_metadata(uri)


def load_parquet_data(uri: str, nrows=None, columns=None) -> pd.DataFrame:
    """Load data from Parquet file"""
    f = get_pyarrow_file(uri)

    if nrows is None:
        table = pq.read_table(f, columns=columns)
    else:
        pf = pq.ParquetFile(f)
        rows = next(pf.iter_batches(batch_size=nrows, columns=columns))
        table = pa.Table.from_batches([rows])

    if table.schema.metadata is not None and b"geo" in table.schema.metadata:
        return _arrow_to_geopandas(table)
    else:
        return table.to_pandas()


def load_geojson_datatypes(url):
    response = load_file(url)
    return response["$defs"]


def get_fs(url_or_path: str) -> AbstractFileSystem:
    """Choose fsspec filesystem by sniffing input url"""
    if isinstance(url_or_path, Path):
        url_or_path = str(url_or_path.absolute())
    parsed = urlparse(url_or_path)

    if parsed.scheme in ("http", "https"):
        if re.search(r"[?&]blocksize=0", url_or_path):
            # We read in chunks. Some origin-server don't support http-range request
            # Add an additional blocksize=0 parameter to your url for a workaround
            return HTTPFileSystem(block_size=0)
        return HTTPFileSystem()

    if parsed.scheme == "s3":
        from s3fs import S3FileSystem

        return S3FileSystem()

    if parsed.scheme == "gs":
        from gcsfs import GCSFileSystem

        return GCSFileSystem()

    return LocalFileSystem()


def is_valid_file_uri(uri, extensions=[]):
    """Determine if the input is a file path or a URL and handle it."""
    if not isinstance(uri, str):
        return None
    elif len(extensions) > 0 and not uri.endswith(tuple(extensions)):
        return None
    elif os.path.exists(uri):
        return uri
    elif is_valid_url(uri):
        return uri
    else:
        raise click.BadParameter(
            "Input must be an existing local file or a URL with protocol: "
            + ",".join(SUPPORTED_PROTOCOLS)
        )


def is_valid_url(url):
    """Check if a URL is valid."""
    try:
        result = urlparse(url)
        return all([result.scheme in SUPPORTED_PROTOCOLS, result.netloc])
    except ValueError:
        return False


def valid_files_folders_for_cli(value, extensions=[]):
    files = []
    for v in value:
        v = is_valid_file_uri(v)
        if os.path.isdir(v):
            for f in os.listdir(v):
                if len(extensions) > 0 and not f.endswith(tuple(extensions)):
                    continue
                if f == "collection.json" or f == "catalog.json":  # likely STAC
                    continue
                files.append(os.path.join(v, f))
        else:
            files.append(v)
    return files


def valid_file_for_cli(ctx, param, value):
    return is_valid_file_uri(value)


def valid_file_for_cli_with_ext(value, extensions):
    return is_valid_file_uri(value, extensions)


def valid_folder_for_cli(ctx, param, value):
    """Determine if the input is a folder."""
    if os.path.exists(value) and os.path.isdir(value):
        return value
    else:
        raise click.BadParameter("Input must be an existing local folder")


def get_collection(data, collection_path=None, basepath=None):
    # If the user provided a collection, enforce using it
    if collection_path is not None:
        return load_file(collection_path)

    # Look if the data contains a fiboa property
    if "fiboa" in data:
        return data.get("fiboa")

    # Look for a collection link in the data and load the collection from there
    links = data.get("links", [])
    for link in links:
        media_type = link.get("type")
        if link.get("rel") == "collection" and (
            media_type is None or media_type == "application/json"
        ):
            href = link.get("href")
            if basepath is not None:
                href = os.path.join(os.path.dirname(basepath), href)
            return load_file(href)

    # No collection found
    return None


def parse_converter_input_files(ctx, param, value):
    if value is None:
        return None
    elif not isinstance(value, tuple):
        raise click.BadParameter("Input files must be a tuple")
    elif len(value) == 0:
        return None

    sources = {}
    for v in value:
        if "|" not in v:
            sources[v] = name_from_uri(v)
        else:
            uri, archive = v.split("|", 2)
            files = archive.split(",")
            sources[uri] = files

    return sources


def parse_map(value, separator="="):
    if value is None:
        return {}
    elif not isinstance(value, tuple):
        raise click.BadParameter("Input files must be a tuple")
    elif len(value) == 0:
        return {}

    mapping = {}
    for v in value:
        key, value = v.split(separator, 2)
        mapping[key] = value

    return mapping


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


def check_ext_schema_for_cli(value, allow_none=False):
    map_ = {}
    for v in value:
        try:
            part = v.split(",", 2)
            map_[part[0]] = None if len(part) < 2 and allow_none else part[1]
        except IndexError:
            optionally = "optionally " if allow_none else ""
            raise click.BadParameter(
                f"Extension schema must be a URL and {optionally}a local file path separated by a comma character"
            )

    return map_


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


def parse_metadata(schema, key):
    if key in schema.metadata:
        return json.loads(schema.metadata[key].decode("utf-8"))
    else:
        str_key = key.decode("utf-8")
        log(f"Parquet file schema does not have a '{str_key}' key", "warning")
        return None


def to_iso8601(dt):
    iso = dt.isoformat()
    if iso.endswith("+00:00"):
        return iso[:-6] + "Z"
    elif re.search(r"[+-]\d{2}:\d{2}$", iso):
        raise ValueError("Timezone offset is not supported")
    else:
        return iso + "Z"


def load_geoparquet_schema(obj):
    if "version" in obj:
        return load_file(GEOPARQUET_SCHEMA.format(version=obj["version"]))
    else:
        return None


def get_core_version(uri):
    match = re.match(VECOREL_SPECIFICAION_PATTERN, uri)
    return match.group(1) if match else None


def get_core_schema(schema_uris):
    for schema_uri in schema_uris:
        version = get_core_version(schema_uri)
        if version is not None:
            return schema_uri, version

    return None, None


def log_extensions(schemas, logger):
    schemas = schemas.copy()
    schemas.sort()
    if len(schemas) <= 1:
        logger("Vecorel extensions: none")
    else:
        logger("Vecorel extensions:")
        for extension in schemas:
            if get_core_version(extension) is not None:
                continue
            logger(f"  - {extension}")
