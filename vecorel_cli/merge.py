from pathlib import Path
from typing import Union

import click
from yarl import URL

from .basecommand import BaseCommand, runnable
from .cli.options import (
    CRS,
    VECOREL_FILES_ARG,
    VECOREL_TARGET,
)
from .encoding.auto import create_encoding
from .registry import Registry
from .vecorel.ops import merge as merge_


class MergeDatasets(BaseCommand):
    cmd_name = "merge"
    cmd_title: str = "Merge Datasets"
    cmd_help: str = f"""
    Merges multiple {Registry.project} datasets to a combined {Registry.project} dataset.

    This simply appends the datasets to each other.
    It does not check for duplicates or other constraints.
    It adds a collection column to discriminate the source of the rows.
    """

    default_crs = "EPSG:4326"

    @staticmethod
    def get_cli_args():
        return {
            "source": VECOREL_FILES_ARG,
            "target": VECOREL_TARGET(),
            "crs": CRS(MergeDatasets.default_crs),
            "include": click.option(
                "--include",
                "-i",
                "includes",
                type=click.STRING,
                multiple=True,
                help="Properties to include in addition to the core properties.",
                show_default=True,
                default=Registry.core_properties,
            ),
            "exclude": click.option(
                "--exclude",
                "-e",
                "excludes",
                type=click.STRING,
                multiple=True,
                help="Core properties to exclude.",
            ),
        }

    @runnable
    def merge(
        self,
        source: list[Union[Path, URL, str]],
        target: Union[Path, str],
        crs=None,
        includes=[],
        excludes=[],
    ):
        if not isinstance(source, list):
            raise ValueError("Source must be a list.")
        if len(source) == 0:
            raise ValueError("No source files provided")
        encodings = [create_encoding(s) for s in source]
        if isinstance(target, str):
            target = Path(target)
        if not crs:
            crs = self.default_crs

        properties = Registry.core_properties.copy()
        properties.extend(includes)
        properties = list(set(properties) - set(excludes))

        gdf, collection = merge_(encodings, crs=crs, properties=properties)

        target = create_encoding(target)
        target.set_collection(collection)
        target.write(gdf, properties=properties)

        return target
