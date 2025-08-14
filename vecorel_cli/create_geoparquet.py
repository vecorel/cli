from pathlib import Path
from typing import Optional, Union

from yarl import URL

from .basecommand import BaseCommand, runnable
from .cli.options import (
    GEOPARQUET_COMPRESSION,
    GEOPARQUET_VERSION,
    PROPERTIES,
    SCHEMA_MAP,
    VECOREL_FILES_ARG,
    VECOREL_TARGET,
)
from .encoding.auto import create_encoding
from .encoding.geoparquet import GeoParquet
from .vecorel.ops import merge
from .vecorel.typing import SchemaMapping


class CreateGeoParquet(BaseCommand):
    cmd_name = "create-geoparquet"
    cmd_title = "Create GeoParquet"
    cmd_help = "Converts to GeoParquet file(s) from other compatible files."
    cmd_final_report = True

    @staticmethod
    def get_cli_args():
        return {
            "source": VECOREL_FILES_ARG,
            "target": VECOREL_TARGET(),
            "properties": PROPERTIES,
            "compression": GEOPARQUET_COMPRESSION,
            "geoparquet_version": GEOPARQUET_VERSION,
            "schema_map": SCHEMA_MAP,
        }

    @runnable
    def create(
        self,
        source: list[Union[Path, URL, str]],
        target: Union[Path, str],
        properties: Optional[Union[tuple[str], list[str]]] = None,
        compression: Optional[str] = None,
        geoparquet_version: Optional[str] = None,
        schema_map: SchemaMapping = {},
    ) -> Path:
        if not isinstance(source, list):
            raise ValueError("Source must be a list.")
        if len(source) == 0:
            raise ValueError("No source files provided")
        if isinstance(target, str):
            target = Path(target)
        if not properties:
            properties = None
        elif isinstance(properties, tuple):
            properties = list(properties)

        # Read source data
        encodings = [create_encoding(s) for s in source]
        # Merge encodings into a single GeoDataFrame
        geodata, collection = merge(encodings, properties=properties, schema_map=schema_map)

        # Write to target
        target_encoding = GeoParquet(target)
        target_encoding.set_collection(collection)
        target_encoding.write(
            geodata,
            compression=compression,
            geoparquet_version=geoparquet_version,
            properties=properties,
            schema_map=schema_map,
        )

        return target
