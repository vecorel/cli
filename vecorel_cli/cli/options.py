import click

from ..const import COMPRESSION_METHODS


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

GEOPARQUET1 = click.option(
    "--geoparquet1",
    "-gp1",
    is_flag=True,
    type=click.BOOL,
    help="GeoParquet only: Enforces generating a v1.0 file. Defaults to v1.1 with bounding box.",
    default=False,
)
