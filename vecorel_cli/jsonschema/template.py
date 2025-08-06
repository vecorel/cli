# fmt: off
from typing import Optional


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
    geojson_properties = set(["id", "bbox", "geometry"])
    properties = set(property_schemas.keys())

    only_collection = set()
    only_properties = set()
    for key, value in collection.items():
        chosen_set = only_collection if value else only_properties
        chosen_set.add(key)

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
                        "not": {"required": toSortedList(geojson_properties)},
                        "properties": {
                            key: property_schemas[key] for key in toSortedList(properties - geojson_properties)
                        }
                    },
                    **{
                        key: property_schemas[key] for key in toSortedList(geojson_properties)
                    }
                }
            },
            "feature_requirements": {
                "type": "object",
                "required": toSortedList(required & geojson_properties),
                "not": {"required": toSortedList(properties - geojson_properties)},
                "properties": {
                    "properties": {
                        "type": "object",
                        "required": toSortedList(required - geojson_properties)
                    }
                }
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
                    } for key in toSortedList(required - geojson_properties - only_collection - only_properties)
                ],
                **check_features({
                    # Check that the features don't contain any properties
                    "not": {"required": toSortedList((properties & only_properties) - (geojson_properties | only_collection))},
                    # Require any properties in the features that can only be used in the properties
                    **check_properties({"required": toSortedList((required & only_properties) - (geojson_properties | only_collection))})
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
