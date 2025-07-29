import os
from pathlib import Path
from typing import Optional, Union

import click

from .basecommand import BaseCommand, runnable
from .cli.util import valid_vecorel_file
from .encoding.auto import create_encoding
from .encoding.geojson import GeoJSON


class CreateGeoJson(BaseCommand):
    cmd_name = "create-geojson"
    cmd_title = "Create GeoJSON"
    cmd_help = "Converts to GeoJSON file(s) from other compatible files."
    cmd_final_report = True

    @staticmethod
    def get_cli_args():
        return {
            "source": click.argument(
                "source",
                nargs=1,
                callback=valid_vecorel_file,
            ),
            "out": click.option(
                "--out",
                "-o",
                type=click.Path(exists=False),
                help="Folder or file to write the data to.",
                required=True,
            ),
            "features": click.option(
                "--features",
                "-f",
                is_flag=True,
                type=click.BOOL,
                help="Create seperate files with a GeoJSON Feature each instead of one file with a GeoJSON FeatureCollection.",
                default=False,
            ),
            "num": click.option(
                "--num",
                "-n",
                type=click.IntRange(min=1),
                help="Number of features to export. Defaults to all.",
                default=None,
            ),
            "indent": click.option(
                "--indent",
                "-i",
                type=click.IntRange(min=0, max=8),
                help="Indentation for JSON files. Defaults to no indentation.",
                default=None,
            ),
        }

    @runnable
    def create(
        source: Union[Path, str],
        target: Union[Path, str],
        split: bool = False,
        num: Optional[int] = None,
        indent: Optional[int] = None,
    ):
        if isinstance(source, str):
            source = Path(source)
        if isinstance(target, str):
            target = Path(target)

        # Read source data
        source_encoding = create_encoding(source)
        collection = source_encoding.get_collection()
        geodata = source_encoding.read(num=num)

        # Write to target
        if split:
            # GeoJSON features
            GeoJSON().write_as_features(geodata, target, collection, indent=indent)
        else:
            # GeoJSON feature collection
            if os.path.isdir(target):
                target = os.path.join(target, "features.json")

            target_encoding = GeoJSON(target)
            target_encoding.write(geodata, collection, indent=indent)

        return target
