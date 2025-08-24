from typing import Optional, Union

from ..validation.base import Validator
from ..vecorel.typing import SchemaMapping
from .schemas import RawSchemas, Schemas, VecorelSchema


class Collection(dict):
    def __init__(self, collection: Optional[dict] = None):
        super().__init__(collection or {})

    def is_empty(self) -> bool:
        return len(self) == 0

    def get_schemas(self) -> Schemas:
        return Schemas(self.get("schemas", {}))

    def get_custom_schemas(self) -> VecorelSchema:
        """
        Get custom schemas from the collection.
        """
        schema = self.get("schemas:custom", {})
        if isinstance(schema, VecorelSchema):
            return schema
        else:
            return VecorelSchema(schema)

    def set_custom_schemas(self, custom_schemas: Union[VecorelSchema, RawSchemas]):
        """
        Set custom schemas in the collection.
        """
        if not isinstance(custom_schemas, VecorelSchema):
            custom_schemas = VecorelSchema(custom_schemas)
        if custom_schemas.is_empty():
            self.pop("schemas:custom", None)
        else:
            self["schemas:custom"] = custom_schemas

    def resolve_schemas(
        self, schema_map: SchemaMapping = {}, validator: Optional[Validator] = None
    ) -> dict[str, VecorelSchema]:
        uris = self.get_schemas().unique_schemas()
        return VecorelSchema.resolve_schema_uris(
            uris,
            schema_map=schema_map,
            validator=validator,
        )

    def merge_schemas(
        self, schema_map: SchemaMapping = {}, validator: Optional[Validator] = None
    ) -> VecorelSchema:
        custom_schemas = self.get_custom_schemas()
        resolved = self.resolve_schemas(
            schema_map=schema_map,
            validator=validator,
        ).values()
        return VecorelSchema.merge_all(*resolved, custom_schemas)

    def get_collection_context(self, schema_map: SchemaMapping = {}) -> list[str]:
        """
        Get the properties that should only be present in the collection metadata.
        """
        schema = self.merge_schemas(schema_map=schema_map)
        return schema.get("collection", {})

    def get_collection_only_properties(self, schema_map: SchemaMapping = {}) -> list[str]:
        """
        Get the properties that should only be present in the collection metadata.
        """
        context = self.get_collection_context(schema_map=schema_map)
        props = []
        for key, value in context.items():
            if value:
                props.append(key)

        # Add the proprietary property for custom schemas as it's not in the core spec,
        # but used in the CLI. Should it be added to the core spec?
        props.append("schemas:custom")

        return props

    def add_schema(self, schema_uri: str):
        schemas = self.get("schemas", {})
        for schema in schemas.values():
            if schema_uri in schema:
                continue
            schema.append(schema_uri)

    def remove_schema(self, schema_uri: str):
        schemas = self.get_schemas()
        for schema in schemas.values():
            schema.remove(schema_uri)
