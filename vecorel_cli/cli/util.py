import os
from urllib.parse import urlparse

import click

from ..const import SUPPORTED_PROTOCOLS
from ..registry import Registry
from ..util import name_from_uri


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


def valid_vecorel_file(ctx, param, value):
    ext = []
    for encoding in Registry.encodings:
        ext += encoding.ext
    return valid_file_for_cli_with_ext(value, ext)


def valid_file_for_cli_with_ext(value, extensions=None):
    return is_valid_file_uri(value, extensions)


def valid_folder_for_cli(ctx, param, value):
    """Determine if the input is a folder."""
    if os.path.exists(value) and os.path.isdir(value):
        return value
    else:
        raise click.BadParameter("Input must be an existing local folder")


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
