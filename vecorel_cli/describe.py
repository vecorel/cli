from pathlib import Path
from typing import Optional, Union

import click
import pandas as pd

from .basecommand import BaseCommand, runnable
from .cli.options import VECOREL_FILE_ARG
from .encoding.auto import create_encoding
from .vecorel.schemas import Schemas


class DescribeFile(BaseCommand):
    cmd_name = "describe"
    cmd_help = "Inspects the content of a Vecorel GeoParquet file."

    @staticmethod
    def get_cli_args():
        return {
            "source": VECOREL_FILE_ARG,
            "num": click.option(
                "--num",
                "-n",
                type=click.IntRange(min=0),
                help="Number of rows to show.",
                show_default=True,
                default=10,
            ),
            "column": click.option(
                "properties",
                "--column",
                "-c",
                type=click.STRING,
                multiple=True,
                help="Column names to show in the excerpt. Can be used multiple times. Shows all by default.",
            ),
        }

    @staticmethod
    def get_cli_callback(cmd):
        def callback(source, num, properties):
            return DescribeFile(source).run(num=num, properties=properties)

        return callback

    def __init__(self, filepath: Union[Path, str]):
        self.filepath = Path(filepath)
        self.cmd_title = f"Describe {self.filepath.resolve()}"

        if not self.filepath.exists():
            raise FileNotFoundError(f"File {self.filepath} does not exist")

        self.encoding = create_encoding(self.filepath)

    @runnable
    def describe(
        self,
        num: int = 10,
        properties: Optional[Union[list[str], tuple[str]]] = None,
    ):
        if isinstance(properties, tuple):
            properties = list(properties)
        if not properties:
            properties = None

        self.success("== FILE SUMMARY ==", style="bold")
        self.summarize()

        self.success("== VERSIONS & EXTENSIONS ==", start="\n", style="bold")
        self.schemas()

        self.success("== COLUMNS ==", start="\n", style="bold")
        self.columns()

        self.success("== COLLECTION DATA ==", start="\n", style="bold")
        self.collection()

        self.success("== PER-GEOMETRY DATA ==", start="\n", style="bold")
        self.data(num, properties=properties)

    def summarize(self):
        summary = self.encoding.get_summary()
        self.print_pretty(summary, strlen=-1)

    def schemas(self):
        schemas = self.encoding.get_schemas()
        count = len(schemas)
        if count == 0:
            self.error("Data not compliant to specification, no version found")
            return
        if count == 1:
            schema = list(schemas.values())[0]
            data = self._schema_to_dict(schema)
        else:
            data = {key: self._schema_to_dict(schema) for key, schema in schemas.items()}
        self.print_pretty(data, strlen=-1)

    def collection(self):
        collection = self.encoding.get_collection()
        if "schemas" in collection:
            collection = collection.copy()
            del collection["schemas"]
        if collection:
            self.print_pretty(collection)
        else:
            self.warning("No collection metadata found")

    def columns(self):
        columns = self.encoding.get_properties()
        if columns:
            for key, value in columns.items():
                self.info(f"{key}: " + ", ".join(value))
        else:
            self.info("File format is not columnar")

    def data(self, num: int = 10, properties: Optional[list[str]] = None):
        if num > 0:
            # Make it so that everything is shown, don't output "..." if there are too many columns or rows
            pd.set_option("display.max_columns", None)
            pd.set_option("display.max_rows", None)
            # Load data
            gdf = self.encoding.read(num=num, properties=properties)
            # Print to console
            self.info(gdf.head(num))
        else:
            self.warning("Omitted")

    def _schema_to_dict(self, schema: Schemas):
        version, uri, extensions = schema.get()
        return {"Version": version, "Extensions": extensions if len(extensions) > 0 else None}
