import click

from ..const import COMPRESSION_METHODS, GEOPARQUET_DEFAULT_VERSION, GEOPARQUET_VERSIONS
from .util import valid_schemas_for_cli


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
    "--schema",
    "-s",
    multiple=True,
    callback=lambda ctx, param, value: valid_schemas_for_cli(value, allow_none=False),
    help="Maps a Vecorel schema URL to a local file. First the URL, then the local file path. Separated with a comma. Example: https://example.com/schema.yaml,/path/to/schema.yaml",
)
