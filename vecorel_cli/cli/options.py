import click

from ..const import COMPRESSION_METHODS, GEOPARQUET_DEFAULT_VERSION, GEOPARQUET_VERSIONS
from .util import valid_schemas_for_cli, valid_vecorel_file, valid_vecorel_files


def CRS(default_value):
    return click.option(
        "--crs",
        type=click.STRING,
        help="GeoParquet only: Coordinate Reference System (CRS) to use for the file.",
        show_default=True,
        default=default_value,
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
    "schemas",
    "--schema",
    "-s",
    multiple=True,
    callback=lambda ctx, param, value: valid_schemas_for_cli(value),
    help="Maps a Vecorel schema URL to a local file. First the URL, then the local file path. Separated with a comma. Example: https://example.com/schema.yaml,/path/to/schema.yaml",
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

VECOREL_FILES_ARG = click.argument(
    "source",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    nargs=-1,
    callback=valid_vecorel_files,
)

VECOREL_FILE_ARG = click.argument(
    "source",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    nargs=1,
    callback=valid_vecorel_file,
)


def VECOREL_TARGET(required=True, folder=False):
    if folder:
        help = "Folder to write the Vecorel file(s) to."
    else:
        help = "File or folder to write the Vecorel file(s) to."
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
