import click

from ..const import COMPRESSION_METHODS, GEOPARQUET_DEFAULT_VERSION, GEOPARQUET_VERSIONS
from ..registry import Registry
from .path_url import PathOrURL
from .util import valid_schemas_for_cli


def CRS(default_value):
    return click.option(
        "--crs",
        type=click.STRING,
        help="GeoParquet only: Coordinate Reference System (CRS) to use for the file.",
        show_default=True,
        default=default_value,
    )


JSON_INDENT = click.option(
    "--indent",
    "-i",
    type=click.IntRange(min=0, max=8),
    help="GeoJSON only: Indentation for JSON files. Defaults to no indentation.",
    default=None,
)


GEOPARQUET_COMPRESSION = click.option(
    "--compression",
    "-pc",
    type=click.Choice(COMPRESSION_METHODS),
    help="GeoParquet only: Compression method",
    show_default=True,
    default="brotli",
)

GEOPARQUET_VERSION = click.option(
    "--geoparquet_version",
    "-pv",
    type=click.Choice(GEOPARQUET_VERSIONS),
    help="GeoParquet only: The GeoParquet version to generate.",
    show_default=True,
    default=GEOPARQUET_DEFAULT_VERSION,
)

SCHEMA_MAP = click.option(
    "schema_map",
    "--schema",
    "-s",
    multiple=True,
    callback=lambda ctx, param, value: valid_schemas_for_cli(value),
    help=f"Maps a {Registry.project} schema URL to a local file. First the URL, then the local file path. Separated with a comma. Example: https://example.com/schema.yaml,/path/to/schema.yaml",
)

PROPERTIES = click.option(
    "properties",
    "--property",
    "-p",
    type=click.STRING,
    multiple=True,
    help="Properties to include. Can be used multiple times. Includes all properties by default.",
    default=None,
)

PY_PACKAGE = click.option(
    "--py-package",
    type=click.STRING,
    help="The Python package to read the converter from",
    show_default=True,
    default=Registry.src_package,
    hidden=True,  # experimental, keep it hidden for now
)

VECOREL_FILES_ARG = click.argument(
    "source",
    type=PathOrURL(multiple=True, extensions=Registry.get_file_extensions()),
    nargs=-1,
    callback=PathOrURL.flatten_tuples,
)

VECOREL_FILE_ARG = click.argument(
    "source",
    type=PathOrURL(extensions=Registry.get_file_extensions()),
    nargs=1,
)


def VECOREL_TARGET(required=True, folder=False):
    if folder:
        help = f"Folder to write the {Registry.project} file(s) to."
    else:
        help = f"File or folder to write the {Registry.project} file(s) to."
    if not required:
        help += " If not provided, the source file will be overwritten."

    return click.option(
        "--target",
        "--out",  # for backward compatibility
        "-o",
        type=click.Path(exists=False, dir_okay=folder, resolve_path=True),
        help=help,
        required=required,
        default=None,
    )


VECOREL_TARGET_CONSOLE = click.option(
    "target",
    "--out",
    "-o",
    type=click.Path(exists=False, dir_okay=False, resolve_path=True),
    help="Path to write the file to. If not provided, prints the data to the console.",
    default=None,
)
