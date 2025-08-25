from typing import Optional

from ..create_jsonschema import CreateJsonSchema
from ..encoding.geojson import GeoJSON
from ..vecorel.typing import SchemaMapping
from .base import Validator


class GeoJSONValidator(Validator):
    def __init__(self, encoding: GeoJSON):
        super().__init__(encoding, mixed_versions=True)

    def _create_jsonschema_command(self) -> CreateJsonSchema:
        return CreateJsonSchema()

    def _validate(self, num: Optional[int] = None, schema_map: SchemaMapping = {}):
        """
        Validate GeoJSON data against the schema.

        :param num: Optional number of records to validate. Only applies to FeatureCollections.
        :param schema_map: Optional mapping of schema names to their definitions.
        """
        # Load data
        try:
            data = self.encoding.read_geojson(num=num, schema_map=schema_map)
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
        jsonschema_instance = self._create_jsonschema_command()
        jsonschemas = {}
        datatypes = {}
        for cid, cschema in schemas.items():
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

        # Validate data
        gj_type = data.get("type")
        errors = []
        if gj_type == "Feature":
            collection = data.get("properties", {}).get("collection")
            if not collection:
                return self.error("Missing the 'collection' property")

            if collection not in jsonschemas:
                return self.error(f"Collection '{collection}' not found in schemas")

            errors = self.validate_json_schema(data, jsonschemas.get(collection))
            for error in errors:
                self.error(error)

        else:  # FeatureCollection
            features = data.get("features", [])
            if len(features) == 0:
                self.warning("No data to validate")
            if not features:
                return self.error("FeatureCollection is empty")

            grouped = {}
            for index, feature in enumerate(features):
                collection = feature.get("properties", {}).get("collection")
                if not collection:
                    self.error(f"Feature {index + 1}: Missing the 'collection' property")
                    continue

                if collection not in jsonschemas:
                    self.error(
                        f"Feature {index + 1}: Collection '{collection}' not found in schemas"
                    )
                    continue

                if collection not in grouped:
                    grouped[collection] = []
                grouped[collection].append(feature)

            for cid, jsonschema in jsonschemas.items():
                # not super clean to just override the features in the original dict,
                # but should be most memory efficient
                data["features"] = grouped.get(cid, [])
                errors = self.validate_json_schema(data, jsonschema)
                for error in errors:
                    self.error(error)
