from pathlib import Path
from typing import Optional, Union

import click

from .basecommand import BaseCommand, runnable
from .cli.options import GEOPARQUET_COMPRESSION, GEOPARQUET_VERSION, SCHEMA_MAP
from .cli.util import valid_vecorel_files
from .encoding.auto import create_encoding
from .encoding.geoparquet import GeoParquet


class CreateGeoParquet(BaseCommand):
    cmd_name = "create-geoparquet"
    cmd_title = "Create GeoParquet"
    cmd_help = "Converts to GeoParquet file(s) from other compatible files."
    cmd_final_report = True

    @staticmethod
    def get_cli_args():
        return {
            "source": click.argument(
                "source",
                nargs=-1,
                callback=valid_vecorel_files
            ),
            "out": click.option(
                "--out",
                "-o",
                type=click.Path(exists=False),
                help="Path to write the data to.",
                required=True,
            ),
            "compression": GEOPARQUET_COMPRESSION,
            "geoparquet_version": GEOPARQUET_VERSION,
            "schemas": SCHEMA_MAP,
        }

    @runnable
    def create(
        self,
        source: list[Union[Path, str]],
        target: Union[Path, str],
        compression: Optional[str] = None,
        geoparquet_version: Optional[str] = None,
        schemas: Optional[dict[str, Path]] = None,
    ):
        if isinstance(target, str):
            target = Path(target)

        # Read source data
        source_encoding = create_encoding(source)



        # Write to target
        target_encoding = GeoParquet(target)
        target_encoding.write(
            geodata,
            collection,
            compression=compression,
            geoparquet_version=geoparquet_version,
            schema_map=schemas,
        )

        return target
