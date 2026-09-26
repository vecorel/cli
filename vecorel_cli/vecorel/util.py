import json
import os
import re
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urlparse

import yaml
from fsspec import AbstractFileSystem
from fsspec.implementations.http import HTTPFileSystem
from fsspec.implementations.local import LocalFileSystem
from yarl import URL

from ..const import SUPPORTED_PROTOCOLS, USER_AGENT

file_cache = {}


def find_differing_crs(crs_values: list, reference=None) -> Optional[int]:
    """The index of the first GeoParquet crs value that differs from the reference
    (by default the first value), None if they all agree. A missing crs is OGC:CRS84."""
    from pyproj import CRS

    def normalize(crs):
        return CRS.from_user_input(crs if crs is not None else "OGC:CRS84")

    reference = normalize(reference) if reference is not None else None
    for i, crs in enumerate(crs_values):
        crs = normalize(crs)
        if reference is None:
            reference = crs
        # GeoParquet coordinates are always x, y regardless of the CRS axis order
        elif not crs.equals(reference, ignore_axis_order=True):
            return i
    return None


def suffix_duplicate_ids(gdf):
    """Number the ids that appear on several rows (id~1, id~2, ...), which turns
    the id column into strings. Null ids are left alone. Returns the frame and
    the number of affected rows."""
    if "id" not in gdf.columns:
        return gdf, 0
    # compare as strings: a mixed-type column can hide repeats (1 vs "1")
    # that the writer merges later
    ids = gdf["id"].astype("string")
    duplicated = ids.duplicated(keep=False) & ids.notna()
    count = int(duplicated.sum())
    if count == 0:
        return gdf, 0
    # a numbered id can collide with one the source already carries (x~1),
    # so number again until nothing repeats
    while duplicated.any():
        # dropna=False keeps the counter an integer when null ids are present
        part = ids.groupby(ids, sort=False, dropna=False).cumcount().add(1)
        ids = ids.mask(duplicated, ids + "~" + part.astype("string"))
        duplicated = ids.duplicated(keep=False) & ids.notna()
    gdf["id"] = ids
    return gdf, count


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
        expected_size = _expected_content_length(f)
        written = 0
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            dst_file.write(chunk)
            written += len(chunk)
    # A truncated response (e.g. the connection dropped mid-download) must be
    # treated as a failure so the caller does not promote the partial file into
    # the cache and later mistake it for a complete download (#46).
    if expected_size is not None and written != expected_size:
        raise OSError(
            f"Incomplete download of {src_uri}: received {written} of {expected_size} bytes"
        )


def _expected_content_length(f) -> Optional[int]:
    """The Content-Length the server promised for an open HTTP file, or None
    when it is unknown or would not match the bytes we read.

    A compressed body is transparently decoded while streaming, so its decoded
    byte count legitimately differs from the Content-Length of the compressed
    payload; in that case we cannot use the header to detect truncation.
    """
    headers = getattr(getattr(f, "r", None), "headers", None)
    if not headers or headers.get("Content-Encoding"):
        return None
    try:
        return int(headers["Content-Length"])
    except (KeyError, TypeError, ValueError):
        return None


def get_fs(url_or_path: Union[str, Path, URL], **kwargs) -> AbstractFileSystem:
    """Choose fsspec filesystem by sniffing input url"""
    if isinstance(url_or_path, Path):
        url_or_path = str(url_or_path.absolute())
    elif isinstance(url_or_path, URL):
        url_or_path = str(url_or_path)
    parsed = urlparse(url_or_path)

    if parsed.scheme in ("http", "https"):
        client_kwargs = kwargs.pop("client_kwargs", {})
        headers = {"User-Agent": USER_AGENT, **client_kwargs.get("headers", {})}
        return HTTPFileSystem(client_kwargs={**client_kwargs, "headers": headers}, **kwargs)

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
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    for unit in units:
        if size < 1024.0 or unit == "PB":
            break
        size /= 1024.0
    return f"{size:.{decimal_places}f} {unit}"


def parse_link_str(link_str: str) -> tuple[str, Optional[str]]:
    """
    Parse a link string into a tuple of title and (optional)URL.
    The string can be in the format "Name <URL>" or just "Name".
    """
    match = re.match(r"^(.*?)(?:\s*<(.+?)>)?$", link_str.strip())
    if match:
        return match.group(1), match.group(2)
    return link_str.strip(), None
