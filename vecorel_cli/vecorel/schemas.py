from __future__ import annotations

import copy
import re
from typing import TYPE_CHECKING, Optional, Union

from ..vecorel.typing import SchemaMapping
from ..vecorel.util import load_file
from .version import is_sdl_supported, sdl_uri

if TYPE_CHECKING:
    from ..validation.base import Validator


class VecorelSchema(dict):
    sdl_pattern = r"https://vecorel.github.io/sdl/v([^/]+)/schema.json"
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
                message = f"Extension {uri} can't be loaded. {e}"
                if validator:
                    validator.error(message)
                else:
                    raise ValueError(message)

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

        self._check_conflicts(other, "required")
        self._check_conflicts(other, "collection")
        self._check_conflicts(other, "properties")

        self["required"] += other.get("required", [])
        self["collection"].update(other.get("collection", {}))
        self["properties"].update(other.get("properties", {}))

    def _check_conflicts(self, other: "VecorelSchema", where: str):
        """Check if there are conflicts between two sets of properties"""
        a = self.get(where)
        b = other.get(where)
        if a is None or b is None:
            return
        if isinstance(a, dict):
            a = a.keys()
        if isinstance(b, dict):
            b = b.keys()
        inter = set(a).intersection(set(b))
        if len(inter) > 0:
            raise ValueError(f"Schema has a conflict: {inter} in '{where}'.")

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
        uri = None
        version = None
        extensions = []
        for schema in self:
            potential_version = self._parse_version(schema)
            if potential_version is None:
                extensions.append(schema)
            else:
                uri = schema
                version = potential_version

        extensions.sort()
        return version, uri, extensions

    def get_core_version(self) -> str:
        version, uri, extensions = self.get()
        return version

    def get_core_schema_uri(self):
        version, uri, extensions = self.get()
        return uri

    def get_extensions(self) -> list[str]:
        version, uri, extensions = self.get()
        return extensions

    def _parse_version(self, schema_uri: str):
        match = re.match(Schemas.spec_pattern, schema_uri)
        return match.group(1) if match else None

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


type RawSchemas = dict[str, list[str]]


class Schemas(dict):
    spec_pattern = r"https://vecorel.github.io/specification/v([^/]+)/schema.yaml"
    spec_schema = "https://vecorel.github.io/specification/v{version}/schema.yaml"

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
