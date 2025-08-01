import json
from typing import Optional, Union

from ..validate_schema import ValidateSchema
from ..vecorel.schemas import Schemas
from ..vecorel.typing import SchemaMapping
from ..vecorel.util import load_file
from ..vecorel.version import is_supported, supported_vecorel_versions


class Validator:
    def __init__(self, encoding: "BaseEncoding"):
        self.encoding = encoding
        self.validated = False
        self.errors = []
        self.warnings = []
        self.infos = []

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

    def validate(self, num: Optional[int] = None, schema_map: SchemaMapping = {}) -> bool:
        self._validate(num=num, schema_map=schema_map)
        self.validated = True
        return self.is_valid()

    def _validate(self, num: Optional[int] = None, schema_map: SchemaMapping = {}):
        raise NotImplementedError("Not implemented")

    def validate_schemas(
        self, groups: dict[str, Schemas], schema_map: SchemaMapping
    ) -> dict[str, dict]:
        if not groups:
            self.error("No schemas provided")
            return {}

        loaded_schemas = {}
        for collection, schemas in groups.items():
            if not isinstance(schemas, Schemas):
                return self.error(
                    f"Collection {collection}: A valid Schemas object must be provided"
                )

            schema_uris = schemas.get_all()
            if len(schema_uris) == 0:
                return self.error(f"Collection {collection}: No schemas provided")

            version = schemas.get_core_version()
            if version is None:
                return self.error(
                    f"Collection {collection}: Vecorel core schema not found in schemas, can't detect Vecorel version"
                )

            if not is_supported(version):
                self.warning(
                    f"Collection {collection}: Vecorel versions differs: Schema reports {version} and supported versions are {supported_vecorel_versions}"
                )

            # Check schemas (core and extensions)
            for uri in schema_uris:
                if uri in loaded_schemas:
                    continue
                try:
                    if uri in schema_map:
                        actual_location = schema_map[uri]
                        self.info(f"Redirecting {uri} to {actual_location}")
                    else:
                        actual_location = uri

                    loaded_schemas[uri] = load_file(actual_location)
                except Exception as e:
                    self.error(f"Collection {collection}: Extension {uri} can't be loaded. {e}")

        return loaded_schemas

    def validate_json_schema(self, obj, schema):
        if isinstance(obj, (bytearray, bytes, str)):
            obj = json.loads(obj)

        validator = ValidateSchema(schema)
        return validator.validate(obj)
