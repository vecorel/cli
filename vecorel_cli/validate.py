from pathlib import Path
from typing import Optional, Union

import click

from .basecommand import BaseCommand, runnable
from .cli.options import SCHEMA_MAP, VECOREL_FILES_ARG
from .encoding.auto import create_encoding
from .registry import Registry
from .validation.base import Validator
from .vecorel.typing import SchemaMapping


class ValidateData(BaseCommand):
    cmd_name = "validate"
    cmd_title: str = "Validator"
    cmd_help: str = f"Validates a {Registry.project} data file."
    cmd_final_report: bool = True

    @staticmethod
    def get_cli_args():
        return {
            "source": VECOREL_FILES_ARG,
            "num": click.option(
                "--num",
                "-n",
                type=click.IntRange(min=-1),
                help="Number of features to validate. Defaults to the first 100. Specify -1 to validate all features.",
                default=100,
            ),
            "schema_map": SCHEMA_MAP,
        }

    @runnable
    def validate_cli(
        self,
        source: list[Union[str, Path]],
        num: int = 100,
        schema_map: SchemaMapping = {},
    ):
        if not isinstance(source, list):
            raise ValueError("Source must be a list.")
        if len(source) == 0:
            raise ValueError("No source files provided")
        if num < 0:
            num = None

        invalid = 0
        for file in source:
            self.info(f"Validating {file}", style="bold", end=": ")
            try:
                result = self.validate(file, num=num, schema_map=schema_map)
                if result.is_valid():
                    self.success("VALID", style="bold")
                else:
                    self.error("INVALID", style="bold")
                    invalid += 1

                for e in result.errors:
                    self.error(e, indent=" - ")
                for e in result.warnings:
                    self.warning(e, indent=" - ")
                for e in result.infos:
                    self.info(e, indent=" - ")

            except Exception as e:
                self.error("UNKNOWN", style="bold")
                self.error(e, indent=" - ")
                invalid += 1
                if self.verbose:
                    raise e

        print()

        if invalid > 0:
            raise ValueError(f"Validation failed for {invalid} files.")
        else:
            return "Validation succeeded for all files."

    def validate_files(
        self,
        files: list[Union[str, Path]],
        num: Optional[int] = None,
        schema_map: SchemaMapping = {},
    ) -> dict[str, Validator]:
        results = {}
        for file in files:
            file = Path(file)
            filepath = str(file.resolve())
            try:
                results[filepath] = self.validate(file, num=num, schema_map=schema_map)
            except Exception as e:
                results[filepath] = [e]

        return results

    def validate(
        self, file: Union[str, Path], num: Optional[int] = None, schema_map: SchemaMapping = {}
    ) -> Validator:
        encoding = create_encoding(file)
        validator = encoding.get_validator()
        validator.validate(num=num, schema_map=schema_map)
        return validator
