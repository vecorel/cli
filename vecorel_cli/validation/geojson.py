from typing import Optional

from ..create_jsonschema import CreateJsonSchema
from ..encoding.geojson import GeoJSON
from ..vecorel.typing import SchemaMapping
from .base import Validator


class GeoJSONValidator(Validator):
    def __init__(self, encoding: GeoJSON):
        super().__init__(encoding, mixed_versions=True)

    def _validate(self, num: Optional[int] = None, schema_map: SchemaMapping = {}):
        # Load data
        try:
            data = self.encoding.read_featurecollection(
                num=num, schema_map=schema_map, hydrate=True
            )
        except Exception as e:
            return self.error(e)

        # Check collection metadata
        collection = self.encoding.get_collection()
        if collection.is_empty():
            return self.error("Collection metadata is empty")

        # Validate schema lists
        schemas = collection.get_schemas()
        self.validate_schemas(schemas)

        # Validate GeoJSON metadata (per collection)
        jsonschema_instance = CreateJsonSchema()
        jsonschemas = {}
        datatypes = {}
        for cid, cschema in schemas.items():
            # todo
            version = cschema.get_core_version()
            if version not in datatypes:
                datatypes[version] = GeoJSON.load_datatypes(GeoJSON.get_datatypes_uri(version))

            vecorel_schema = cschema.merge_schemas(
                schema_map=schema_map,
                custom_schemas=collection.get_custom_schemas(),
                validator=self,
            )

            jsonschemas[cid] = jsonschema_instance.create_from_dict(
                vecorel_schema, datatypes[version]
            )

        # Skip validating data
        if num == 0:
            return

        # Validate data
        features = data.get("features", [])
        if len(features) == 0:
            return self.error("Must contain at least one Feature")

        for index, feature in enumerate(features):
            collection = feature.get("properties", {}).get("collection")
            if not collection:
                self.error(f"Feature {index} is missing 'collection' property")
                continue

            jsonschema = jsonschemas.get(collection)
            errors = self.validate_json_schema(feature, jsonschema)
            for error in errors:
                self.error(error)
