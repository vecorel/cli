import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import click
import pandas as pd

from ..const import SUPPORTED_PROTOCOLS
from ..registry import Registry
from ..vecorel.util import name_from_uri


def is_valid_file_uri(uri, extensions=[]):
    """Determine if the input is a file path or a URL and handle it."""
    if not isinstance(uri, str):
        raise click.BadParameter("Input must be a string representing a file path or URL")
    elif len(extensions) > 0 and not uri.endswith(tuple(extensions)):
        raise click.BadParameter(
            f"File '{uri}' must have one of the following extensions: {', '.join(extensions)}"
        )
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


def get_files(value, extensions=[]):
    files = []
    extensions = tuple(extensions)
    for v in value:
        v = is_valid_file_uri(v)
        if os.path.isdir(v):
            for f in os.listdir(v):
                if len(extensions) > 0 and not f.endswith(extensions):
                    continue
                if f == "collection.json" or f == "catalog.json":  # likely STAC
                    continue
                files.append(os.path.join(v, f))
        else:
            files.append(v)
    return files


def valid_file(ctx, param, value):
    return is_valid_file_uri(value)


def valid_vecorel_file(ctx, param, value) -> Path:
    ext = Registry.get_vecorel_extensions()
    return is_valid_file_uri(value, extensions=ext)


def valid_vecorel_files(ctx, param, value) -> list[Path]:
    ext = Registry.get_vecorel_extensions()

    files = []
    if isinstance(value, str):
        files = [value]
    elif isinstance(value, tuple):
        files = list(value)
    elif isinstance(value, list):
        files = value

    if len(files) == 0:
        raise click.BadParameter("No files provided.")

    actual_files = []
    for file in files:
        if is_valid_file_uri(file, extensions=ext):
            actual_files.append(Path(file))

    return actual_files


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


def parse_map(value: tuple[str], separator: str = "=") -> dict[str, str]:
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


def valid_schemas_for_cli(value: tuple[str]) -> dict[str, Path]:
    map_ = {}
    for v in value:
        part = v.split(",", 2)

        if len(part) != 2:
            raise click.BadParameter(
                "Schema must be a URL and a local file path separated by a comma character."
            )
        if not is_valid_url(part[0]):
            raise click.BadParameter(f"Schema URL '{part[0]}' is not a valid URL.")

        p = Path(part[1])
        if not p.exists():
            raise click.BadParameter(f"Local schema file '{p}' does not exist.")

        map_[part[0]] = p

    return map_


def display_pandas_unrestricted(max_colwidth: Optional[int] = 50):
    pd.set_option("display.max_columns", None)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_colwidth", max_colwidth)
