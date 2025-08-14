from pathlib import Path
from typing import Optional

import click
import pandas as pd

from ..vecorel.util import is_url, name_from_uri


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
                "Schema must be a URL and a local file path, separated by a comma character."
            )
        if not is_url(part[0]):
            raise click.BadParameter(f"Schema URL '{part[0]}' is not a valid URL.")

        p = Path(part[1])
        if not p.exists():
            raise click.BadParameter(f"Local schema file '{p.resolve()}' does not exist.")

        map_[part[0]] = p

    return map_


def display_pandas_unrestricted(max_colwidth: Optional[int] = 50):
    pd.set_option("display.max_columns", None)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_colwidth", max_colwidth)
