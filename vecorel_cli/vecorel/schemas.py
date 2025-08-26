from __future__ import annotations

import copy
import re
from typing import TYPE_CHECKING, Optional, Union

from ..vecorel.typing import RawSchemas, SchemaMapping
from ..vecorel.util import load_file
from .version import is_sdl_supported, sdl_uri

if TYPE_CHECKING:
    from ..validation.base import Validator


class VecorelSchema(dict):
    sdl_pattern = r"https://vecorel.org/sdl/v([^/]+)/schema.json"
    sdl_schema = sdl_uri

    @staticmethod
    def merge_all(*schemas) -> VecorelSchema:
        """Merge multiple schemas into one"""
        if len(schemas) == 0:
            return VecorelSchema()
        else:
            base = copy.deepcopy(schemas[0])
            base.pop("$id", None)
            for schema in schemas[1:]:
                base.merge(schema)

        return base

    @staticmethod
    def resolve_schema_uris(
        uris: set[str], schema_map: SchemaMapping = {}, validator: Optional[Validator] = None
    ) -> dict[str, VecorelSchema]:
        # Load all schemas
        loaded = {}
        for uri in uris:
            try:
                if uri in schema_map:
                    actual_location = schema_map[uri]
                    if validator:
                        validator.info(f"Redirecting {uri} to {actual_location}")
                else:
                    actual_location = uri

                data = load_file(actual_location)
                loaded[uri] = VecorelSchema(data, identifier=uri)
            except Exception as e:
                message = f"Schema {uri} can't be loaded. {e}"
                if validator:
                    validator.error(message)
                else:
                    raise ValueError(message) from e

        return loaded

    def __init__(self, schema={}, identifier: Optional[str] = None):
        super().__init__(schema)

        self.migrate()
        if identifier is not None:
            self["$id"] = identifier
        if not self.is_empty():
            sdl_version = self.get_sdl_version()
            is_sdl_supported(sdl_version, raise_exception=True)

    def get_sdl_version(self):
        sdl = self.get("$schema", "")
        match = re.match(VecorelSchema.sdl_pattern, sdl)
        return match.group(1) if match else None

    def is_empty(self) -> bool:
        return len(self.get("properties", {})) == 0 and len(self.get("required", {})) == 0

    def migrate(self):
        """Migrate schema to a new version"""
        if not self.get("$schema"):
            self["$schema"] = VecorelSchema.sdl_schema
        if "required" not in self:
            self["required"] = []
        if "collection" not in self:
            self["collection"] = {}
        if "properties" not in self:
            self["properties"] = {}

    def merge(self, other: "VecorelSchema"):
        """Merge another schema into this one, in-place."""
        if isinstance(other, dict):
            other = VecorelSchema(other)

        if other.is_empty():
            return

        if self.get_sdl_version() != other.get_sdl_version():
            raise ValueError("Schemas have different SDL versions, can't merge.")

        # Merge required properties
        self["required"] = list(set(self["required"]) | set(other.get("required", [])))

        # Merge collection details
        other_collection = other.get("collection", {}).items()
        for key, value in other_collection:
            if key not in self["collection"]:
                self["collection"][key] = value
            else:
                self_value = self["collection"][key]
                if self_value != value:
                    raise ValueError(
                        f"Schema has conflicts in 'collection': Property '{key}' has values '{self_value}' and '{value}'."
                    )
                else:
                    pass  # exists as is, no action needed

        # Merge actual schemas for properties
        self["properties"] = self._merge_properties(
            self["properties"], other.get("properties", {}), "properties"
        )

    def _merge_properties(self, a: dict, b: dict, path: str = "") -> dict:
        all_properties = set(a.keys()) | set(b.keys())
        a = a.copy()
        for key in all_properties:
            if key in a:
                if key in b:
                    # merge schemas
                    a[key] = self._merge_json_schema(a[key], b[key], f"{path}.{key}")
                else:
                    pass  # doesn't exist in other schema, keep as is
            else:
                # doesn't exist in this schema, just add it from the other schema
                a[key] = b[key]
        return a

    def _merge_json_schema(self, a: dict, b: dict, path: str = "") -> dict:
        """Merge two JSON schemas"""
        if not isinstance(a, dict) or not isinstance(b, dict):
            raise ValueError(
                f"Conflict in '{path}': Cannot merge types '{type(a)}' and '{type(b)}'."
            )

        a = a.copy()
        all_keys = set(a.keys()) | set(b.keys())
        for key in all_keys:
            if key == "additionalProperties":
                # We need to handle additionalProperties separately as it has a default value
                ap1 = a.get("additionalProperties", False)
                ap2 = b.get("additionalProperties", False)
                if isinstance(ap1, dict) and isinstance(ap2, dict):
                    a[key] = self._merge_json_schema(ap1, ap2, f"{path}.additionalProperties")
                elif a[key] is False or b[key] is False:
                    a[key] = False
                elif a[key] is True and isinstance(b[key], dict):
                    a[key] = b[key]
                else:
                    pass  # a is good as is, no action needed
            elif key not in b:
                continue
            elif key not in a:
                a[key] = b[key]
            else:
                p = f"{path}.{key}"
                match key:
                    case "$schema":
                        pass  # ignore for now. todo: Properly check versions
                    case "required":
                        a[key] = list(set(a[key]) | set(b[key]))
                    case ("enum", "geometryTypes"):
                        a[key] = list(set(a[key]) & set(b[key]))
                    case ("items", "contains"):
                        a[key] = self._merge_json_schema(a[key], b[key], p)
                    case ("properties", "patternProperties"):
                        a[key] = self._merge_properties(a[key], b[key], p)
                    case ("minLength", "minimum", "exclusiveMinimum", "minItems", "minProperties"):
                        a[key] = max(a[key], b[key])
                    case ("maxLength", "maximum", "exclusiveMaximum", "maxItems", "maxProperties"):
                        a[key] = min(a[key], b[key])
                    case ("deprecated", "uniqueItems"):
                        if b[key]:
                            a[key] = True
                    case _:  # description, type, format, pattern, default
                        if a[key] == b[key]:
                            a[key] = b[key]
                        else:
                            raise ValueError(f"Conflict in '{p}': '{a[key]}' != '{b[key]}'")

        if "minimum" in a and "exclusiveMinimum" in a:
            raise ValueError(
                f"Conflict in '{path}': 'minimum' and 'exclusiveMinimum' cannot coexist"
            )
        if "maximum" in a and "exclusiveMaximum" in a:
            raise ValueError(
                f"Conflict in '{path}': 'maximum' and 'exclusiveMaximum' cannot coexist"
            )

        return a

    def _check_conflicts(self, other: "VecorelSchema", where: str):
        """Check if there are conflicts between two sets of properties"""
        a = self.get(where)
        b = other.get(where)
        if a is None or b is None:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            k1 = a.keys()
            k2 = b.keys()
            intersection = set(k1).intersection(set(k2))
            for key in intersection:
                if a[key] != b[key]:
                    raise ValueError(
                        f"Schema has conflicts: {', '.join(intersection)} in '{where}', e.g. for '{key}' values are '{a[key]}' and '{b[key]}'."
                    )

    def pick(self, property_names: list[str], rename: dict[str, str] = {}) -> "VecorelSchema":
        """Pick and rename schemas for specific properties"""
        required = self.get("required", [])
        collection = self.get("collection", {})
        properties = self.get("properties", {})

        result = self.copy()
        result["required"] = []
        result["collection"] = {}
        result["properties"] = {}
        for prop in property_names:
            prop2 = rename[prop] if prop in rename else prop
            if prop in required:
                result["required"].append(prop2)
            if prop in collection:
                result["collection"][prop2] = collection[prop]
            if prop in properties:
                result["properties"][prop2] = properties[prop]

        return VecorelSchema(result)


class CollectionSchemas(set):
    @staticmethod
    def parse_version(schema_uri: str, pattern: str):
        match = re.match(pattern, schema_uri)
        return match.group(1) if match else None

    @staticmethod
    def parse_schemas(schemas: list[str], spec_pattern: re.Pattern) -> tuple[str, str, list[str]]:
        uri = None
        version = None
        extensions = []
        for schema in schemas:
            potential_version = CollectionSchemas.parse_version(schema, spec_pattern)
            if potential_version is None:
                extensions.append(schema)
            else:
                uri = schema
                version = potential_version

        extensions.sort()
        return version, uri, extensions

    def __init__(
        self, schemas: Union[list[str], set[str], "CollectionSchemas"] = [], collection=None
    ):
        super().__init__(schemas)
        # ID of the collection
        if collection is None and isinstance(schemas, CollectionSchemas):
            self.collection = schemas.collection
        else:
            self.collection = collection

    def is_empty(self) -> bool:
        return len(self) == 0

    def get(self) -> tuple[str, str, list[str]]:
        return CollectionSchemas.parse_schemas(self, Schemas.spec_pattern)

    def get_core_version(self) -> str:
        version, uri, extensions = self.get()
        return version

    def get_core_schema_uri(self):
        version, uri, extensions = self.get()
        return uri

    def get_extensions(self) -> list[str]:
        version, uri, extensions = self.get()
        return extensions

    def resolve_schemas(
        self,
        schema_map: SchemaMapping = {},
        validator: Validator = None,
    ) -> dict[str, VecorelSchema]:
        return VecorelSchema.resolve_schema_uris(
            self,
            schema_map=schema_map,
            validator=validator,
        )

    def merge_schemas(
        self,
        schema_map: SchemaMapping = {},
        custom_schemas: dict = {},
        validator: Optional[Validator] = None,
    ) -> VecorelSchema:
        resolved = self.resolve_schemas(
            schema_map=schema_map,
            validator=validator,
        ).values()
        return VecorelSchema.merge_all(*resolved, custom_schemas)


class Schemas(dict):
    spec_pattern = r"https://vecorel.org/specification/v([^/]+)/schema.yaml"
    spec_schema = "https://vecorel.org/specification/v{version}/schema.yaml"

    @staticmethod
    def get_core_uri(version: str) -> str:
        return Schemas.spec_schema.format(version=version)

    def __init__(self, schemas: Union[RawSchemas, "Schemas"] = {}):
        self.loaded = {}
        if isinstance(schemas, Schemas):
            self.update(schemas)
        else:
            for collection, schemas in schemas.items():
                self[collection] = CollectionSchemas(schemas, collection)

    def get_all(self) -> list[CollectionSchemas]:
        return list(self.values())

    def add_all(self, schemas: "Schemas"):
        self.update(schemas)

    def is_empty(self) -> bool:
        return len(self) == 0

    def add(self, collection: str, schemas: list[str]) -> CollectionSchemas:
        obj = CollectionSchemas(schemas, collection)
        self[collection] = obj
        return obj

    def unique_schemas(self) -> set[str]:
        """Get a set of unique schema URIs across all collections."""
        unique = set()
        for schemas in self.values():
            unique.update(schemas)
        return unique
