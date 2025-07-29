from pathlib import Path
from typing import Union

import click
import pandas as pd

from .basecommand import BaseCommand, runnable
from .cli.options import CRS, GEOPARQUET_COMPRESSION, GEOPARQUET_VERSION
from .encoding.auto import create_encoding
from .jsonschema.util import (
    is_schema_empty,
    merge_schemas,
    pick_schemas,
)
from .registry import Registry


class MergeDatasets(BaseCommand):
    cmd_name = "merge"
    cmd_title: str = "Merge Datasets"
    cmd_help: str = """
    Merges multiple Vecorel datasets to a combined Vecorel dataset.

    This simply appends the datasets to each other.
    It does not check for duplicates or other constraints.
    It adds a collection column to discriminate the source of the rows.
    """

    default_crs = "EPSG:4326"

    @staticmethod
    def get_cli_args():
        return {
            "datasets": click.argument("datasets", nargs=-1, type=click.Path(exists=True)),
            "out": click.option(
                "--out",
                "-o",
                type=click.Path(exists=False),
                help="Path to write the GeoParquet file to.",
                required=True,
            ),
            "crs": CRS(MergeDatasets.default_crs),
            "include": click.option(
                "--include",
                "-i",
                "includes",
                type=click.STRING,
                multiple=True,
                help="Additional column names to include.",
                show_default=True,
                default=Registry.core_columns,
            ),
            "exclude": click.option(
                "--exclude",
                "-e",
                "excludes",
                type=click.STRING,
                multiple=True,
                help="Default column names to exclude.",
            ),
            "compression": GEOPARQUET_COMPRESSION,
            "geoparquet_version": GEOPARQUET_VERSION,
        }

    @runnable
    def merge(
        self,
        datasets,
        out: Union[Path, str],
        crs=None,
        includes=[],
        excludes=[],
        compression=None,
        geoparquet_version=False,
    ):
        if not crs:
            crs = self.default_crs
        if isinstance(out, str):
            out = Path(out)

        columns = Registry.core_columns.copy()
        columns.extend(includes)
        columns = list(set(columns) - set(excludes))

        # Load the datasets
        all_gdf = []
        custom_schemas = {}
        all_schemas = {}
        for dataset in datasets:
            # Load the dataset
            encoding = create_encoding(dataset)
            gdf = encoding.read(columns=columns)
            collection = encoding.get_collection()

            # Change the CRS if necessary
            gdf.to_crs(crs=crs, inplace=True)

            # Add collection column to each dataset
            if collection is not None and "collection" in collection:
                gdf["collection"] = collection["collection"]
            elif "collection" not in gdf.columns:
                gdf["collection"] = str(dataset)

            # todo: add more checks
            schemas = collection.get("schemas", {})
            all_schemas.update(schemas)

            # Merge custom schemas
            custom_schema = collection.get("custom_schemas", {})
            custom_schemas = merge_schemas(custom_schemas, custom_schema)

            all_gdf.append(gdf)

        merged = pd.concat(all_gdf, ignore_index=True)

        # Remove empty columns
        merged.dropna(axis=1, how="all", inplace=True)
        columns = list(merged.columns)
        columns.sort()

        # Create collection metadata
        collection = {
            "schemas": all_schemas,
        }

        # Add custom schemas
        custom_schemas = pick_schemas(custom_schemas, columns)
        if not is_schema_empty(custom_schemas):
            collection["custom_schemas"] = custom_schemas

        # Write the merged dataset to the output file
        target = create_encoding(out)
        target.write(
            merged,
            collections=collection,
            compression=compression,
            geoparquet_version=geoparquet_version,
        )

        return out
