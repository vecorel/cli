# ruff: noqa
# todo: remove this comment once the code has been updated

import json
from pathlib import Path
from typing import Optional, Union
from urllib.request import Request, urlopen

import click
import referencing
from jsonschema.exceptions import ValidationError
from jsonschema.protocols import Validator
from jsonschema.validators import Draft7Validator, Draft202012Validator

from .basecommand import BaseCommand, runnable
from .cli.util import valid_file_for_cli, valid_files_folders_for_cli
from .vecorel.util import load_file


class ValidateSchema(BaseCommand):
    cmd_name = "validate-schema"
    cmd_title: str = "Schema Validator"
    cmd_help: str = "Validates a Vecorel schema file."

    @staticmethod
    def get_cli_args():
        return {
            "files": click.argument(
                "files",
                nargs=-1,
                callback=lambda ctx, param, value: valid_files_folders_for_cli(
                    value, ["yaml", "yml"]
                ),
            ),
            "metaschema": click.option(
                "--metaschema",
                "-m",
                callback=valid_file_for_cli,
                help="Vecorel SDL metaschema to validate against.",
                default=None,
            ),
        }

    @staticmethod
    def get_cli_callback(cmd):
        def callback(files, metaschema):
            return ValidateSchema(metaschema).run(files)

        return callback

    def __init__(self, metaschema: Optional[Union[Path, dict]] = None):
        self.validator: Optional[Validator] = None
        if isinstance(metaschema, Path):
            metaschema = load_file(metaschema)
        if isinstance(metaschema, dict):
            self.validator = self.create_validator(metaschema)

    @runnable
    def validate_cli(self, files: list[Union[Path, str]]) -> bool:
        results = self.validate_files(files)
        if len(results) == 0:
            self.log("No files to validate", "error")
            return False

        invalid_count = 0
        for filepath, errors in results.items():
            self.log(f"Validating {filepath}", "info")
            if len(errors) > 0:
                for error in errors:
                    self._log2(error, "error")
                invalid_count += 1
            else:
                self._log2("VALID", "success")

        return invalid_count == 0

    def validate_files(self, files: list[Union[Path, str]]) -> dict:
        mapping = {}
        for file in files:
            file = Path(file)
            errors = self.validate_file(file)
            filepath = str(file.resolve().absolute())
            mapping[filepath] = errors

        return mapping

    def validate_file(self, filepath: Union[Path, str]) -> list[ValidationError]:
        schema = load_file(filepath)
        if not isinstance(schema, dict):
            return [ValidationError("Schema is not an object")]

        if self.validator is None:
            metaschema_uri = schema.get("$schema")
            if metaschema_uri:
                metaschema = load_file(metaschema_uri)
                validator = self.create_validator(metaschema)
            else:
                return [
                    ValidationError(
                        "No metaschema provided and no $schema found in the schema file"
                    )
                ]
        else:
            validator = self.validator

        return self.validate(schema, validator)

    def validate(self, obj: dict, validator: Validator) -> list[ValidationError]:
        return list(sorted(validator.iter_errors(obj), key=lambda e: e.path))

    def create_validator(self, schema) -> Validator:
        if schema["$schema"] == "http://json-schema.org/draft-07/schema#":
            instance = Draft7Validator
        else:
            instance = Draft202012Validator

        return instance(
            schema,
            format_checker=instance.FORMAT_CHECKER,
            registry=referencing.Registry(retrieve=ValidateSchema.retrieve_remote_schema),
        )

    def _log2(self, text: Union[Exception, str], status="info", nl=True, **kwargs):
        self.log(" - " + str(text), status, nl, **kwargs)

    @staticmethod
    def retrieve_remote_schema(uri: str):
        request = Request(uri)
        with urlopen(request) as response:
            return referencing.Resource.from_contents(
                json.load(response),
                default_specification=referencing.jsonschema.DRAFT202012,
            )
