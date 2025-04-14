from pathlib import Path
from typing import Optional, Union

import click
import pandas as pd

from .basecommand import BaseCommand, runnable
from .cli.util import valid_vecorel_file
from .encoding.auto import create_encoding
from .vecorel.schemas import Schemas


class DescribeFile(BaseCommand):
    cmd_name = "describe"
    cmd_help = "Inspects the content of a Vecorel GeoParquet file."

    @staticmethod
    def get_cli_args():
        return {
            "file": click.argument(
                "file",
                nargs=1,
                callback=valid_vecorel_file,
            ),
            "num": click.option(
                "--num",
                "-n",
                type=click.IntRange(min=0),
                help="Number of rows to show.",
                show_default=True,
                default=10,
            ),
            "column": click.option(
                "--column",
                "-c",
                type=click.STRING,
                multiple=True,
                help="Column names to show in the excerpt. Can be used multiple times. Shows all by default.",
            ),
        }

    @staticmethod
    def get_cli_callback(cmd):
        def callback(file, num, column):
            return DescribeFile(file).run(num=num, columns=column)

        return callback

    def __init__(self, filepath: Union[Path, str]):
        self.cmd_title = f"Describe {filepath}"
        self.filepath = Path(filepath)

        if not self.filepath.exists():
            raise FileNotFoundError(f"File {self.filepath} does not exist")

        self.encoding = create_encoding(self.filepath)

    @runnable
    def describe(
        self,
        num: int = 10,
        columns: Optional[Union[list[str], tuple[str]]] = None,
    ):
        if isinstance(columns, tuple):
            columns = list(columns)
        if len(columns) == 0:
            columns = None

        self.log("== FILE SUMMARY ==", "success")
        self.summarize()

        self.log("\n== VERSIONS & EXTENSIONS ==", "success")
        self.schemas()

        self.log("\n== COLUMNS ==", "success")
        self.columns()

        self.log("\n== COLLECTION DATA ==", "success")
        self.collection()

        self.log("\n== PER-GEOMETRY DATA ==", "success")
        self.data(num, columns)

    def summarize(self):
        summary = self.encoding.get_summary()
        self.print_pretty(summary, strlen=-1)

    def schemas(self):
        schemas = self.encoding.get_schemas()
        count = len(schemas)
        if count == 0:
            self.log("Data not compliant to specification, no version found", "error")
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
            self.log("No collection metadata found", "warning")

    def columns(self):
        columns = self.encoding.get_columns()
        if columns:
            for key, value in columns.items():
                self.log(f"{key}: ", "debug", nl=False)
                self.log(", ".join(value))
        else:
            self.log("File format is not columnar")

    def data(self, num: int = 10, columns: Optional[list[str]] = None):
        if num > 0:
            # Make it so that everything is shown, don't output "..." if there are too many columns or rows
            pd.set_option("display.max_columns", None)
            pd.set_option("display.max_rows", None)
            # Load data
            gdf = self.encoding.read(num=num, columns=columns)
            # Print to console
            self.log(gdf.head(num))
        else:
            self.log("Omitted", "warning")

    def _schema_to_dict(self, schema: Schemas):
        version, uri, extensions = schema.get()
        return {"Version": version, "Extensions": extensions if len(extensions) > 0 else None}

    # strlen = -1 disables truncation
    def print_pretty(self, value: dict, depth=0, strlen=50):
        prefix = "  " * depth
        if hasattr(value, "to_dict"):
            value = value.to_dict()
        if isinstance(value, dict):
            if depth <= 1:
                if depth > 0:
                    self.log("")
                for key, value in value.items():
                    self.log(prefix + key + ": ", "debug", nl=False)
                    self.print_pretty(value, depth=depth + 1, strlen=strlen)
            else:
                self.log(f"object (omitted, {len(value)} key/value pairs)", "warning")
        elif isinstance(value, list):
            if depth <= 1:
                if depth > 0:
                    self.log("")
                for item in value:
                    self.log(prefix + "- ", nl=False)
                    self.print_pretty(item, depth=depth + 1, strlen=strlen)
            else:
                self.log(f"array (omitted, {len(value)} elements)", "warning")
        elif isinstance(value, str):
            length = len(value)
            if strlen >= 0 and length > strlen:
                self.log(value[:strlen], nl=False)
                if len(value) > strlen:
                    self.log(f"... ({length - strlen} chars omitted)", "warning")
            else:
                self.log(value)
        else:
            self.log(value)
