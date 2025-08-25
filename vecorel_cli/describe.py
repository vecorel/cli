from pathlib import Path
from typing import Optional, Union

import click
from yarl import URL

from .basecommand import BaseCommand, runnable
from .cli.options import VECOREL_FILE_ARG
from .cli.util import display_pandas_unrestricted
from .encoding.auto import create_encoding
from .registry import Registry
from .vecorel.schemas import CollectionSchemas


class DescribeFile(BaseCommand):
    cmd_name = "describe"
    cmd_help = f"Inspects the content of a {Registry.project} GeoParquet file."

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
            "verbose": click.option(
                "--verbose",
                "-v",
                is_flag=True,
                help="Show more detailed information.",
                default=False,
            ),
        }

    @staticmethod
    def get_cli_callback(cmd):
        def callback(source, num, properties, verbose):
            return DescribeFile(source).run(num=num, properties=properties, verbose=verbose)

        return callback

    def __init__(self, filepath: Union[Path, URL, str]):
        if isinstance(filepath, str):
            filepath = Path(filepath)
        if isinstance(filepath, Path):
            filepath = filepath.resolve()

        self.filepath = filepath
        self.cmd_title = f"Describe {self.filepath}"
        self.encoding = create_encoding(self.filepath)

        if not self.encoding.exists():
            raise FileNotFoundError(f"'{self.filepath}' is not available")

    @runnable
    def describe(
        self,
        num: int = 10,
        properties: Optional[Union[list[str], tuple[str]]] = None,
        verbose: bool = False,
    ):
        if isinstance(properties, tuple):
            properties = list(properties)
        if not properties:
            properties = None

        self.success("FILE SUMMARY", style="underline")
        self.summarize()

        self.success("VERSIONS & EXTENSIONS", start="\n", style="underline")
        self.schemas()

        self.success("COLUMNS", start="\n", style="underline")
        self.columns()

        self.success("COLLECTION DATA", start="\n", style="underline")
        self.collection(verbose=verbose)

        self.success("PER-GEOMETRY DATA", start="\n", style="underline")
        self.data(num, properties=properties)

    def summarize(self):
        summary = self.encoding.get_summary()
        self.print_pretty(summary, strlen=-1)

    def schemas(self):
        collection = self.encoding.get_collection()
        schemas = collection.get_schemas()
        count = len(schemas)
        if count == 0:
            self.error("Data not compliant to the specification or outdated, no version found")
            return
        if count == 1:
            schema = list(schemas.values())[0]
            data = self._schema_to_dict(schema)
            self.print_pretty(data, strlen=-1)
        else:
            for cid, schema in schemas.items():
                self.info(f"Collection '{cid}':", style="bold")
                data = self._schema_to_dict(schema)
                self.print_pretty(data, depth=1, max_depth=2, strlen=-1)

        nl = "\n" if count > 1 else ""
        self.print_pretty(
            {f"{nl}Custom Schemas": "Yes" if "schemas:custom" in collection else "No"}
        )

    def collection(self, verbose: bool = False):
        collection = self.encoding.get_collection().copy()
        collection.pop("schemas", None)
        if not verbose:
            collection.pop("schemas:custom", None)
        if collection:
            self.print_pretty(
                collection,
                max_depth=3 if verbose else 1,
                strlen=-1 if verbose else 50,
            )
        else:
            self.warning("Nothing found")

    def columns(self):
        columns = self.encoding.get_properties()
        if columns:
            for key, value in columns.items():
                self.print_pretty({key: ", ".join(value)}, strlen=-1)
        else:
            self.info("File format is not columnar")

    def data(self, num: int = 10, properties: Optional[list[str]] = None):
        if num > 0:
            # Make it so that everything is shown, don't output "..." if there are too many columns or rows
            display_pandas_unrestricted()
            # Load data
            gdf = self.encoding.read(num=num, properties=properties)
            # Print to console
            self.info(gdf.head(num))
        else:
            self.warning("Omitted")

    def _schema_to_dict(self, schema: CollectionSchemas):
        version, uri, extensions = schema.get()
        obj = {
            "Version": version,
            "Extensions": extensions if len(extensions) > 0 else None,
        }
        return obj
