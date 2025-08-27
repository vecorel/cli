import importlib
import os
from typing import Sequence

import click
import pandas as pd

from .basecommand import BaseCommand, runnable
from .cli.options import PY_PACKAGE
from .cli.util import display_pandas_unrestricted
from .conversion.base import BaseConverter
from .registry import Registry


class Converters(BaseCommand):
    cmd_name = "converters"
    cmd_title = "List of Converters"
    cmd_help = "Lists all available data converters."
    default_max_colwidth = 35
    base_class = BaseConverter

    @staticmethod
    def get_cli_args():
        return {
            "providers": click.option(
                "--providers",
                "-p",
                is_flag=True,
                type=click.BOOL,
                help="Show the provider name(s)",
                default=False,
            ),
            "sources": click.option(
                "--sources",
                "-s",
                is_flag=True,
                type=click.BOOL,
                help="Show the source(s)",
                default=False,
            ),
            "verbose": click.option(
                "--verbose",
                "-v",
                is_flag=True,
                type=click.BOOL,
                help="Do not shorten the content of the columns",
                default=False,
            ),
            "py-package": PY_PACKAGE,
        }

    @runnable
    def converters(self, providers=False, sources=False, verbose=False, py_package=None, **kwargs):
        """
        Lists all available converters through the CLI.
        """
        if py_package:
            Registry.src_package = py_package

        columns = {"short_name": "Short Title", "license": "License"}
        if providers:
            columns["providers"] = "Provider(s)"
        if sources:
            columns["sources"] = "Source(s)"

        keys = list(columns.keys())
        converters = self.list_all(keys)
        df = pd.DataFrame.from_dict(converters, orient="index", columns=keys)
        df.rename(columns=columns, inplace=True)

        display_pandas_unrestricted(None if verbose else self.default_max_colwidth)

        if not df.empty:
            self.info(df)
        else:
            self.warning("No converters found.")

    def get_module(self, name=None):
        name = f".datasets.{name}" if name else ".datasets"
        return importlib.import_module(name, package=Registry.src_package)

    def get_path(self) -> str:
        module = self.get_module()
        return module.__path__[0]

    def get_class(self, name):
        if not self.is_converter(f"{name}.py"):
            raise ValueError(f"Converter with id '{name}' is not an allowed converter filename.")

        base_class = self.base_class
        try:
            module = self.get_module(name)
        except ModuleNotFoundError as e:
            raise ValueError(f"Converter '{name}' not found") from e

        try:
            clazz = next(
                v
                for v in module.__dict__.values()
                if type(v) is type
                and issubclass(v, base_class)
                and base_class.__name__ not in v.__name__
            )
            return clazz(self)
        except StopIteration:
            raise ImportError(
                f"No valid converter class for '{name}' found. Class must inherit from {base_class.__name__})."
            )

    def list_ids(self) -> list:
        files = os.listdir(self.get_path())
        ids = [f[:-3] for f in files if self.is_converter(f)]
        return ids

    def list_all(self, keys: Sequence[str] = ("short_name", "license")) -> dict:
        converters = {}
        for id in self.list_ids():
            obj = {}
            try:
                converter = self.load(id)

                for key in keys:
                    value = getattr(converter, key.lower())

                    if key == "sources" and isinstance(value, dict):
                        value = ", ".join(list(value.keys()))
                    elif key == "license" and isinstance(value, dict):
                        value = value["href"]
                    elif key == "providers" and isinstance(value, list):
                        value = ", ".join(list(map(lambda x: x["name"], value)))

                    obj[key] = value

                converters[id] = obj
            except ValueError:
                pass
        return converters

    def load(self, name):
        return self.get_class(name)

    def is_converter(self, filename):
        """
        Checks if the given dataset is a valid converter filename.
        """
        return (
            filename.endswith(".py")
            and not filename.startswith(".")
            and not filename.startswith("__")
            and filename not in Registry.ignored_datasets
        )
