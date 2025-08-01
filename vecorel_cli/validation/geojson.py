from typing import Optional

from ..create_jsonschema import CreateJsonSchema
from ..encoding.geojson import GeoJSON
from ..vecorel.typing import SchemaMapping
from .base import Validator


class GeoJSONValidator(Validator):
    def __init__(self, encoding: GeoJSON):
        super().__init__(encoding)

    def _validate(self, num: Optional[int] = None, schema_map: SchemaMapping = {}):
        # Load data
        try:
            data = self.encoding.read_featurecollection(num=num, hydrate=True)
        except Exception as e:
            return self.error(e)

        # Validate schema listings
        schemas = self.encoding.get_schemas()
        loaded_schemas = self.validate_schemas(schemas, schema_map)

        version = schemas.get_core_version()
        datatypes = GeoJSON.get_datatypes(version)

        core_schema_uri = schemas.get_core_schema_uri()
        core_schema = loaded_schemas[core_schema_uri]
        jsonschema = CreateJsonSchema()
        schema = jsonschema.create_from_dict(core_schema, datatypes)

        # Load extensions
        ext_errors = []
        extensions = {}
        for ext in schemas:
            try:
                json_schema = jsonschema.create_from_dict(schemas[ext], datatypes)
                extensions[ext] = lambda obj: self.validate_json_schema(obj, json_schema)
            except Exception as error:
                extensions[ext] = None
                ext_errors.append(f"Failed to load extension {ext}: {str(error)}")

        for error in ext_errors:
            self.error(error)

        # Validate
        if len(features) == 0:
            self.error("Must contain at least one Feature")
            return False

        for index, feature in enumerate(features):
            errors = self.validate_json_schema(feature, schema)
            if len(errors) > 0:
                valid = False

            label = feature.get("id", f"index: {index}")

            if not valid:
                for error in errors:
                    self.error(f"{label}: {error}")
            else:
                for ext, validate_fn in extensions.items():
                    if validate_fn:
                        ext_errors = validate_fn(feature)
                        if len(ext_errors) > 0:
                            for error in ext_errors:
                                self.error(f"{label} (ext {ext}): {error}")
                            valid = False
                    else:
                        self.warning(f"{label}: Extension {ext} SKIPPED")
                if valid and len(features) > 1:
                    self.success(f"{label}: VALID")

        return valid
