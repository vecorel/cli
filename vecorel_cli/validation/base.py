from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Optional, Union

from ..validate_schema import ValidateSchema
from ..vecorel.schemas import Schemas
from ..vecorel.typing import SchemaMapping
from ..vecorel.version import is_supported

if TYPE_CHECKING:
    from ..encoding.base import BaseEncoding


class Validator:
    def __init__(self, encoding: BaseEncoding, mixed_versions: bool = False):
        self.encoding = encoding
        self.validated = False
        self.supports_mixed_versions = mixed_versions
        self.errors = []
        self.warnings = []
        self.infos = []
        self.required_schemas: list[Union[str, re.Pattern]] = []

    def info(self, message: str):
        self.infos.append(message)
        return None

    def warning(self, warning: str):
        self.warnings.append(warning)
        return None

    def error(self, error: Union[Exception, str]):
        if isinstance(error, str):
            error = Exception(error)
        self.errors.append(error)
        return None

    def is_valid(self) -> bool:
        if not self.validated:
            raise RuntimeError("Validation has not been performed yet. Call validate() first.")

        return len(self.errors) == 0

    def set_required_schemas(self, patterns: list[Union[str, re.Pattern]]):
        self.required_schemas = patterns

    def validate(self, num: Optional[int] = None, schema_map: SchemaMapping = {}) -> bool:
        self._validate(num=num, schema_map=schema_map)
        self.validated = True
        return self.is_valid()

    def _validate(self, num: Optional[int] = None, schema_map: SchemaMapping = {}):
        raise NotImplementedError("Not implemented")

    def validate_schemas(self, groups: Schemas):
        if groups.is_empty():
            return self.error("No schemas provided")

        last_core_version = None
        for schema in groups.get_all():
            if schema.is_empty():
                self.error(f"Collection '{schema.collection}': No schemas provided")
                continue

            version, uri, extensions = schema.get()
            if version is None:
                self.error(
                    f"Collection '{schema.collection}': Vecorel core schema not found in schemas, can't detect Vecorel version"
                )
                continue

            if last_core_version and version != last_core_version:
                if not self.supports_mixed_versions:
                    self.error(
                        f"Vecorel versions differ: found {last_core_version} and {version}, but mixed versions are NOT supported"
                    )
                else:
                    self.warning(
                        f"Vecorel versions differ: found {last_core_version} and {version}, but mixed versions are supported"
                    )

            is_supported(version, raise_exception=True)

            last_core_version = version

            # Check whether all required schemas are present, not needed in vecorel but other specs
            if len(self.required_schemas) == 0:
                return

            for pattern in self.required_schemas:
                found = False
                for ext in extensions:
                    if (isinstance(pattern, re.Pattern) and pattern.search(ext)) or pattern == ext:
                        found = True
                        break

                if not found:
                    p = pattern.pattern if isinstance(pattern, re.Pattern) else pattern
                    self.error(f"Collection '{schema.collection}': Required schema {p} not found")

    def _create_validate_schema_command(self, schema) -> ValidateSchema:
        return ValidateSchema(schema)

    def validate_json_schema(self, obj, schema):
        if isinstance(obj, (bytearray, bytes, str)):
            obj = json.loads(obj)

        validator = self._create_validate_schema_command(schema)
        return validator.validate(obj)
