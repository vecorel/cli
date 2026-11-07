import pytest

from vecorel_cli.vecorel.collection import Collection
from vecorel_cli.vecorel.ops import merge_collections
from vecorel_cli.vecorel.schemas import VecorelSchema

SDL = "https://vecorel.org/sdl/v0.2.0/schema.json"


def _schema(**properties):
    return VecorelSchema({"$schema": SDL, "properties": properties})


def _merge(a, b, union=False):
    merged = _schema(**a)
    merged.merge(_schema(**b), union=union)
    return merged["properties"]


A = {
    "land_type": {"type": "string", "enum": ["a", "b"]},
    "score": {"type": "float", "minimum": 0, "maximum": 10},
    "tags": {"type": "array", "items": {"type": "string", "maxLength": 5}, "uniqueItems": True},
    "size": {"type": "uint8", "maximum": 50},
}
B = {
    "land_type": {"type": "string", "enum": ["b", "c"]},
    "score": {"type": "float", "minimum": 2, "maximum": 20},
    "tags": {"type": "array", "items": {"type": "string", "maxLength": 3}},
    "size": {"type": "uint8"},
}


def test_merging_the_schemas_of_one_collection_restricts_the_values():
    # the data must satisfy both schemas
    merged = _merge(A, B)
    assert merged["land_type"]["enum"] == ["b"]
    assert merged["score"]["minimum"] == 2
    assert merged["score"]["maximum"] == 10
    assert merged["tags"]["items"]["maxLength"] == 3
    assert merged["tags"]["uniqueItems"] is True
    assert merged["size"]["maximum"] == 50


def test_a_union_keeps_the_values_of_both_schemas_valid():
    # the data satisfies one of the schemas
    merged = _merge(A, B, union=True)
    assert merged["land_type"]["enum"] == ["a", "b", "c"]
    assert merged["score"]["minimum"] == 0
    assert merged["score"]["maximum"] == 20
    assert merged["tags"]["items"]["maxLength"] == 5
    assert "uniqueItems" not in merged["tags"]
    assert "maximum" not in merged["size"]


def test_differing_values_still_conflict():
    with pytest.raises(ValueError, match="Conflict in 'properties.score.type'"):
        _merge({"score": {"type": "float"}}, {"score": {"type": "string"}})


@pytest.mark.parametrize("union", [False, True])
def test_additional_properties_in_one_schema_only(union):
    a = {"meta": {"type": "object", "additionalProperties": True}}
    b = {"meta": {"type": "object"}}
    merged = _merge(a, b, union=union)
    assert merged["meta"]["additionalProperties"] is (True if union else False)


def test_merged_datasets_keep_the_enum_values_of_each():
    collections = [
        Collection({"schemas": {"c1": []}, "schemas:custom": _schema(land_type=A["land_type"])}),
        Collection({"schemas": {"c2": []}, "schemas:custom": _schema(land_type=B["land_type"])}),
    ]
    merged = merge_collections(collections)
    assert merged.get_custom_schemas()["properties"]["land_type"]["enum"] == ["a", "b", "c"]


def _required_example(b_custom):
    a = _schema(
        **{
            "inspire:id": {"type": "string"},
            "meta": {
                "type": "object",
                "required": ["source"],
                "properties": {"source": {"type": "string"}},
            },
        }
    )
    a["required"] = ["inspire:id"]
    collections = [
        Collection({"schemas": {"a": []}, "schemas:custom": a}),
        Collection({"schemas": {"b": []}, **({"schemas:custom": b_custom} if b_custom else {})}),
    ]
    return merge_collections(collections).get_custom_schemas()


def test_merged_datasets_only_require_what_every_dataset_requires():
    b = _schema(meta={"type": "object", "properties": {"source": {"type": "string"}}})
    custom = _required_example(b)
    assert custom["required"] == []
    assert "required" not in custom["properties"]["meta"]


def test_a_dataset_without_custom_schemas_requires_none_of_their_properties():
    assert _required_example(None)["required"] == []


def test_one_collection_requires_what_any_of_its_schemas_requires():
    a = _schema(meta={"type": "object", "required": ["source"]})
    a["required"] = ["meta"]
    b = _schema(meta={"type": "object", "required": ["kind"]})
    b["required"] = ["id"]
    a.merge(b)
    assert sorted(a["required"]) == ["id", "meta"]
    assert sorted(a["properties"]["meta"]["required"]) == ["kind", "source"]


def test_a_union_drops_items_contains_and_format_only_one_schema_has():
    a = {
        "tags": {"type": "array", "items": {"type": "string"}, "contains": {"const": "x"}},
        "mail": {"type": "string", "format": "email"},
    }
    b = {"tags": {"type": "array"}, "mail": {"type": "string"}}
    merged = _merge(a, b, union=True)
    assert merged["tags"] == {"type": "array"}
    assert merged["mail"] == {"type": "string"}
    # one collection's schemas still restrict each other
    merged = _merge(a, b)
    assert merged["tags"]["items"] == {"type": "string"}
    assert merged["mail"]["format"] == "email"
