import os
from pathlib import Path
from typing import Optional, Union

import click

from .basecommand import BaseCommand, runnable
from .cli.options import PROPERTIES, VECOREL_FILE_ARG, VECOREL_TARGET
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
            "source": VECOREL_FILE_ARG,
            "target": VECOREL_TARGET(folder=True),
            "properties": PROPERTIES,
            "features": click.option(
                "split",
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
        self,
        source: Union[Path, str],
        target: Union[Path, str],
        properties: Optional[Union[tuple[str], list[str]]] = None,
        split: bool = False,
        num: Optional[int] = None,
        indent: Optional[int] = None,
    ):
        if isinstance(source, str):
            source = Path(source)
        if isinstance(target, str):
            target = Path(target)
        if not split and target.is_dir():
            target = target / "features.json"
        if isinstance(properties, tuple):
            properties = list(properties)

        # Read source data
        source_encoding = create_encoding(source)
        geodata = source_encoding.read(num=num, properties=properties, hydrate=split)
        collection = source_encoding.get_collection()

        # Write to target
        if split:
            # GeoJSON features
            geodata.to_crs(epsg=4326, inplace=True)
            i = 0
            for obj in geodata.iterfeatures():
                i += 1

                obj = GeoJSON.fix_geo_interface(obj)
                id_ = obj.get("id", i)
                target_file = target / f"{id_}.json"

                print(target_file.absolute())

                target_encoding = GeoJSON(target_file)
                target_encoding.set_collection(collection)
                target_encoding.write_feature(obj, properties=properties, indent=indent)
        else:
            # GeoJSON feature collection
            target_encoding = GeoJSON(target)
            target_encoding.set_collection(collection)
            target_encoding.write(geodata, properties=properties, indent=indent)

        return target
