# fmt: off
from typing import Optional

from ..encoding.geojson import GeoJSON


def check_properties(schema: dict) -> dict:
    return {
        "type": "object",
        "properties": {
            "properties": schema
        }
    }


def check_features(schema: dict) -> dict:
    return {
        "type": "object",
        "properties": {
            "features": {
                "type": "array",
                "items": schema
            }
        }
    }


def not_required(items: set[str]) -> dict:
    if len(items) == 0:
        return {}
    return {"not": {"required": list(items)}}


# Sets have an unpredictable order, so we convert to a list and sort them
# so that the output is deterministic / consistent.
def toSortedList(items: set) -> list:
    """Return a sorted list from a set."""
    return sorted(items)


def jsonschema_template(
    property_schemas: dict,
    required: set[str],
    collection: dict[str, bool],
    schema_id: Optional[str] = None,
):
    properties = set(property_schemas.keys())

    only_collection = set()
    only_properties = set()
    for key, value in collection.items():
        chosen_set = only_collection if value else only_properties
        chosen_set.add(key)

    top_level_feature = GeoJSON.feature_properties | only_collection

    # The properties that are defined in fiboa, but are also GeoJSON top-level properties
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "if": {
            # Check whether the GeoJSON is a FeatureCollection, otherwise it must be a Feature
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {
                    "const": "FeatureCollection"
                }
            }
        },
        "then": {
            # Schema for Feature Collections
            "type": "object",
            "allOf": [
                {"$ref": "https://geojson.org/schema/FeatureCollection.json"},
                {"$ref": "#/$defs/featurecollection_schemas"},
                {"$ref": "#/$defs/featurecollection_requirements"},
                {"$ref": "#/$defs/featurecollection_uniqueness"}
            ]
        },
        "else": {
            # Schema for Features
            "allOf": [
                {"$ref": "https://geojson.org/schema/Feature.json"},
                {"$ref": "#/$defs/feature_schemas"},
                {"$ref": "#/$defs/feature_requirements"}
            ]
        },
        "$defs": {
            "feature_schemas": {
                "type": "object",
                "properties": {
                    "properties": {
                        "type": "object",
                        "properties": {
                            key: property_schemas[key] for key in toSortedList(properties - top_level_feature) if key in property_schemas
                        },
                        **not_required(toSortedList(only_collection))
                    },
                    **{
                        key: property_schemas[key] for key in toSortedList(top_level_feature) if key in property_schemas
                    }
                }
            },
            "feature_requirements": {
                "type": "object",
                "required": toSortedList(required & top_level_feature),
                "properties": {
                    "properties": {
                        "type": "object",
                        "required": toSortedList(required - top_level_feature)
                    }
                },
                **not_required(toSortedList(only_properties - GeoJSON.feature_properties))
            },
            "featurecollection_schemas": check_features({"$ref": "#/$defs/feature_schemas"}),
            "featurecollection_requirements": {
                # Check that the required collection properties are present
                "type": "object",
                "required": list(required & only_collection),
                # Check that the non-collectio, non-features-only and non-geojson properties are either
                # present in the collection or in the feature properties
                "allOf": [
                    {
                        "oneOf": [
                            {"required": [key]},
                            check_features(check_properties({"required": [key]}))
                        ]
                    } for key in toSortedList(required - top_level_feature - only_properties)
                ],
                **check_features({
                    # Check that the features don't contain any properties
                    **not_required(toSortedList((properties & only_properties) - top_level_feature)),
                    # Require any properties in the features that can only be used in the properties
                    **check_properties({"required": toSortedList((required & only_properties) - top_level_feature)})
                })
            },
            "featurecollection_uniqueness": {
                "allOf": [
                    {
                        # Check whether the property exists in the collection
                        "if": {"required": [key]},
                        # Then don't allow this property in the features
                        "then": check_features(check_properties({
                            "not": {"required": [key]}
                        }))
                    } for key in toSortedList(properties)
                ]
            }
        }
    }
    if schema_id:
        schema["$id"] = schema_id
    return schema
