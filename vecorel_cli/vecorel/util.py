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
from yarl import URL

from ..const import SUPPORTED_PROTOCOLS

file_cache = {}


def load_file(uri: Union[Path, URL, str]) -> dict:
    """Load files from various sources"""
    if isinstance(uri, Path):
        uri = str(uri.absolute())
    if isinstance(uri, URL):
        uri = str(uri)

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


def stream_file(fs, src_uri, dst_file, chunk_size=10 * 1024 * 1024):
    with fs.open(src_uri, mode="rb", block_size=0) as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            dst_file.write(chunk)


def get_fs(url_or_path: Union[str, Path, URL], **kwargs) -> AbstractFileSystem:
    """Choose fsspec filesystem by sniffing input url"""
    if isinstance(url_or_path, Path):
        url_or_path = str(url_or_path.absolute())
    elif isinstance(url_or_path, URL):
        url_or_path = str(url_or_path)
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


def name_from_uri(url):
    if "://" in url:
        try:
            url = urlparse(url).path
        except ValueError:
            pass
    return os.path.basename(url)


def is_url(url: str) -> bool:
    """Check if a URL is valid."""
    try:
        result = urlparse(url)
        return all([result.scheme in SUPPORTED_PROTOCOLS, result.netloc])
    except ValueError:
        return False


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
