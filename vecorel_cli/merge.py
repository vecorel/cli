from pathlib import Path
from typing import Optional, Union

import click
from yarl import URL

from .basecommand import BaseCommand, runnable
from .cli.options import (
    VECOREL_FILES_ARG,
    VECOREL_TARGET,
)
from .encoding.auto import create_encoding
from .encoding.base import BaseEncoding
from .encoding.geoparquet import GeoParquet
from .registry import Registry
from .vecorel.ops import merge as merge_


class MergeDatasets(BaseCommand):
    cmd_name = "merge"
    cmd_title: str = "Merge Datasets"
    cmd_help: str = f"""
    Merges multiple {Registry.project} datasets to a combined {Registry.project} dataset.

    This simply appends the datasets to each other.
    Ids that repeat within a collection are reported, but not changed.
    Each feature keeps its collection, which is stored in a column if the
    datasets have multiple collections.

    Local GeoParquet files that are all in the target CRS are merged with DuckDB,
    which doesn't need to fit the data into memory. All other datasets are merged in memory.
    """

    default_crs = "EPSG:4326"
    first_crs = "first"
    engines = ["auto", "duckdb", "geopandas"]

    @staticmethod
    def get_cli_args():
        return {
            "source": VECOREL_FILES_ARG,
            "target": VECOREL_TARGET(),
            "crs": click.option(
                "--crs",
                type=click.STRING,
                help=f"GeoParquet only: Coordinate Reference System (CRS) to use for the file. Use '{MergeDatasets.first_crs}' for the CRS of the first dataset.",
                show_default=True,
                default=MergeDatasets.default_crs,
            ),
            "include": click.option(
                "--include",
                "-i",
                "includes",
                type=click.STRING,
                multiple=True,
                help="Properties to include in addition to the core properties. Includes all properties if not given.",
            ),
            "exclude": click.option(
                "--exclude",
                "-e",
                "excludes",
                type=click.STRING,
                multiple=True,
                help="Properties to exclude.",
            ),
            "engine": click.option(
                "--engine",
                type=click.Choice(MergeDatasets.engines),
                help="The engine to merge with, 'auto' uses DuckDB if possible.",
                show_default=True,
                default="auto",
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
        engine="auto",
    ):
        if not isinstance(source, list):
            raise ValueError("Source must be a list.")
        if len(source) == 0:
            raise ValueError("No source files provided")
        if engine not in self.engines:
            raise ValueError(f"Engine must be one of {', '.join(self.engines)}")
        encodings = [create_encoding(s) for s in source]
        for encoding in encodings:
            if not encoding.exists():
                raise FileNotFoundError(f"File not found: {encoding.uri}")
        if isinstance(target, str):
            target = Path(target)
        target = create_encoding(target)
        if not crs:
            crs = self.default_crs
        elif crs == self.first_crs:
            crs = None

        properties = None
        if includes:
            properties = list(set(Registry.core_properties) | set(includes))

        blocker = self.get_duckdb_blocker(encodings, target, crs)
        if engine == "duckdb" and blocker:
            raise ValueError(f"Can't merge with DuckDB: {blocker}")

        if engine == "duckdb" or (engine == "auto" and blocker is None):
            from .conversion.duckdb import DuckDBBaseConverter

            if excludes:
                if properties is None:
                    properties = self.get_available_properties(encodings)
                properties = list(set(properties) - set(excludes))

            self.info("Merging with DuckDB")
            DuckDBBaseConverter().merge_parquet(
                [e.uri for e in encodings],
                target.uri,
                properties=properties,
                suffix_duplicate_ids=False,
                strict=False,
            )
        else:
            if engine == "auto":
                self.info(f"Merging in memory, as {blocker}")
            gdf, collection = merge_(
                encodings, crs=crs, properties=properties, log=self, excludes=excludes
            )
            target.set_collection(collection)
            target.write(gdf, properties=properties)

        return target

    @staticmethod
    def get_available_properties(encodings: list[BaseEncoding]) -> list[str]:
        properties = set()
        for encoding in encodings:
            columns = encoding.get_properties()
            if columns is None:
                columns = encoding.read().columns
            properties |= set(columns)
            properties |= set(encoding.get_collection().keys())
        return list(properties)

    @staticmethod
    def get_duckdb_blocker(
        encodings: list[BaseEncoding], target: BaseEncoding, crs=None
    ) -> Optional[str]:
        """
        The reason why the datasets can't be merged with DuckDB, None if they can.
        A `crs` of None stands for the CRS of the first dataset.
        """
        from .conversion.duckdb import _equal_crs, _normalize_crs

        for encoding in [*encodings, target]:
            if not isinstance(encoding, GeoParquet) or not isinstance(encoding.uri, Path):
                return "DuckDB only merges local GeoParquet files"

        reference = _normalize_crs(crs) if crs else None
        for encoding in encodings:
            geo = encoding.get_geoparquet_metadata() or {}
            column = geo.get("columns", {}).get(geo.get("primary_column"), {})
            source_crs = _normalize_crs(column.get("crs"))
            if reference is None:
                reference = source_crs
            elif not _equal_crs(source_crs, reference):
                return "the datasets must be reprojected to a common CRS"

        return None
