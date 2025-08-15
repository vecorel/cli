from vecorel_cli.vecorel.collection import Collection
from vecorel_cli.vecorel.ops import merge_collections
from vecorel_cli.vecorel.schemas import Schemas, VecorelSchema


def test_merge_collections():
    # Create mock collections
    collection1 = Collection(
        {
            "schemas": {"c1": ["https://example.com/schema1.yaml"]},
            "schemas:custom": {
                "$schema": "https://vecorel.org/sdl/v0.2.0/schema.json",
                "properties": {
                    "determination_datetime": {"type": "date-time"},
                },
            },
        }
    )
    collection2 = Collection(
        {
            "schemas": {"c2": ["https://example.com/schema2.yaml"]},
            "schemas:custom": {
                "$schema": "https://vecorel.org/sdl/v0.2.0/schema.json",
                "required": ["inspire:id"],
                "collection": {"inspire:id": False},
                "properties": {
                    "inspire:id": {"type": "string", "minLength": 1},
                },
            },
        }
    )
    collection3 = Collection(
        {
            "schemas": {"c2": ["https://example.com/schema2.yaml"]},
            "schemas:custom": {"custom_schema2": {"type": "AnotherCustomFeature"}},
        }
    )

    merged_collection = merge_collections([collection1, collection2, collection3])

    assert "schemas" in merged_collection
    assert merged_collection.get_schemas() == Schemas(
        {"c1": ["https://example.com/schema1.yaml"], "c2": ["https://example.com/schema2.yaml"]}
    )

    assert "schemas:custom" in merged_collection
    assert merged_collection.get_custom_schemas() == VecorelSchema(
        {
            "$schema": "https://vecorel.org/sdl/v0.2.0/schema.json",
            "required": ["inspire:id"],
            "collection": {"inspire:id": False},
            "properties": {
                "determination_datetime": {"type": "date-time"},
                "inspire:id": {"type": "string", "minLength": 1},
            },
        }
    )
