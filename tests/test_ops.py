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


def test_merge_collections_keeps_collection_properties():
    # https://github.com/vecorel/cli/issues/26
    schemas = {"c1": ["https://example.com/schema1.yaml"]}
    collection1 = Collection(
        {
            "schemas": schemas,
            "source_name": "Example",
            "source_version": "1.0",
            "only_in_first": "x",
        }
    )
    collection2 = Collection(
        {
            "schemas": schemas,
            "source_name": "Example",
            "source_version": "2.0",
        }
    )

    merged = merge_collections([collection1])
    assert merged.get("source_name") == "Example"
    assert merged.get("source_version") == "1.0"
    assert merged.get("only_in_first") == "x"

    merged = merge_collections([collection1, collection2])
    # present in all collections with the same value => kept
    assert merged.get("source_name") == "Example"
    # conflicting values => dropped
    assert "source_version" not in merged
    # missing in one collection => dropped
    assert "only_in_first" not in merged

    merged = merge_collections([collection1], properties=["only_in_first"])
    assert "source_name" not in merged
    assert merged.get("only_in_first") == "x"
