import re

import pytest

from vecorel_cli.vecorel.collection import Collection
from vecorel_cli.vecorel.ops import check_versions, merge_collections, warn_missing_required
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
            # only collection2 requires it; the features of collection1 don't have it
            "required": [],
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


def test_merge_collections_unites_schemas_of_a_collection():
    core = "https://vecorel.org/specification/v0.1.0/schema.yaml"
    ext = "https://example.com/ext.yaml"
    merged = merge_collections(
        [Collection({"schemas": {"c1": [core, ext]}}), Collection({"schemas": {"c1": [core]}})]
    )
    assert merged.get_schemas() == Schemas({"c1": [core, ext]})

    other_core = "https://vecorel.org/specification/v0.2.0/schema.yaml"
    with pytest.raises(ValueError, match="conflicting core schemas"):
        merge_collections(
            [Collection({"schemas": {"c1": [core]}}), Collection({"schemas": {"c1": [other_core]}})]
        )

    fiboa = "https://fiboa.org/specification/v{}/schema.yaml"
    with pytest.raises(ValueError, match="conflicting versions of a schema"):
        merge_collections(
            [
                Collection({"schemas": {"c1": [core, fiboa.format("0.2.0")]}}),
                Collection({"schemas": {"c1": [core, fiboa.format("0.3.0")]}}),
            ]
        )
    # other collections may use another version
    merge_collections(
        [
            Collection({"schemas": {"c1": [core, fiboa.format("0.2.0")]}}),
            Collection({"schemas": {"c2": [core, fiboa.format("0.3.0")]}}),
        ]
    )


def test_merge_collections_warns_about_collection_only_properties():
    class Log:
        warnings = []

        def warning(self, message):
            self.warnings.append(message)

    core = "https://vecorel.org/specification/v0.1.0/schema.yaml"
    custom = {"properties": {"producer": {"type": "string"}}, "collection": {"producer": True}}
    collections = [
        Collection({"schemas": {"c1": [core]}, "schemas:custom": custom, "producer": "A", "x": 1}),
        Collection({"schemas": {"c2": [core]}, "schemas:custom": custom, "producer": "B", "x": 2}),
    ]
    log = Log()
    merged = merge_collections(collections, log=log)
    assert "producer" not in merged
    # x is not collection-only, so it goes back into the features, which the caller handles
    assert log.warnings == [
        "Collection-only properties differ between the datasets and are removed: producer"
    ]


def test_warn_missing_required_collection_only_properties(tmp_path):
    class Log:
        warnings = []

        def warning(self, message):
            self.warnings.append(message)

    core = "https://vecorel.org/specification/v0.1.0/schema.yaml"
    ext = "https://example.com/producer/v0.1.0/schema.yaml"
    path = tmp_path / "schema.yaml"
    path.write_text(
        "$schema: https://vecorel.org/sdl/v0.2.0/schema.json\n"
        "required: [producer]\n"
        "collection: {producer: true}\n"
        "properties: {producer: {type: string}}\n"
    )
    schema_map = {ext: path}
    properties = ["id", "geometry", "collection"]
    collections = [
        Collection({"schemas": {"c1": [core, ext]}, "producer": "A"}),
        Collection({"schemas": {"c2": [core, ext]}, "producer": "A"}),
    ]
    merged = merge_collections(collections, properties=properties)
    assert "producer" not in merged

    log = Log()
    warn_missing_required(collections, properties, schema_map, log)
    message = "Required properties are not included, the merged file will be invalid: producer"
    assert log.warnings == [message]

    with pytest.raises(ValueError, match=message):
        warn_missing_required(collections, properties, schema_map, strict=True)


def test_merge_collections_uses_the_schema_map(tmp_path):
    class Log:
        warnings = []

        def warning(self, message):
            self.warnings.append(message)

    # the extension is only available through the schema map
    core = "https://vecorel.org/specification/v0.1.0/schema.yaml"
    ext = "https://example.com/producer/v0.1.0/schema.yaml"
    path = tmp_path / "schema.yaml"
    path.write_text(
        "$schema: https://vecorel.org/sdl/v0.2.0/schema.json\n"
        "required: [producer]\n"
        "collection: {producer: true}\n"
        "properties: {producer: {type: string}}\n"
    )
    schema_map = {ext: path}
    collections = [
        Collection({"schemas": {"c1": [core, ext]}, "producer": "A"}),
        Collection({"schemas": {"c2": [core, ext]}, "producer": "B"}),
    ]
    message = "Collection-only properties differ between the datasets and are removed: producer"

    log = Log()
    merged = merge_collections(collections, log=log, schema_map=schema_map)
    assert "producer" not in merged
    assert log.warnings == [message]

    with pytest.raises(ValueError, match=message):
        merge_collections(collections, strict=True, schema_map=schema_map)


def test_check_versions():
    core1 = "https://vecorel.org/specification/v0.1.0/schema.yaml"
    core2 = "https://vecorel.org/specification/v0.2.0/schema.yaml"
    ext1 = "https://example.com/ext/v0.1.0/schema.yaml"
    ext2 = "https://example.com/ext/v0.2.0/schema.yaml"
    other = "https://example.com/other/v0.5.0/schema.yaml"

    # the same versions, and different extensions, are fine
    check_versions(
        [
            Collection({"schemas": {"a": [core1, ext1]}}),
            Collection({"schemas": {"b": [core1, ext1, other]}}),
        ]
    )

    # different versions fail, also across collections and datasets
    with pytest.raises(ValueError, match=re.escape(f"{core1}; {core2}")):
        check_versions([Collection({"schemas": {"a": [core1], "b": [core2]}})])
    with pytest.raises(ValueError, match=re.escape(f"{ext1}; {ext2}")):
        check_versions(
            [
                Collection({"schemas": {"a": [core1, ext1]}}),
                Collection({"schemas": {"b": [core1, ext2]}}),
            ]
        )


# Not sorted, so that the order of a set would differ from it
ORDERED_KEYS = ["zeta", "alpha", "mu", "beta", "omega", "kappa", "delta", "gamma"]


def _merged_metadata(folder):
    import json
    from pathlib import Path

    from vecorel_cli.encoding.geojson import VecorelJSONEncoder

    sdl = "https://vecorel.org/sdl/v0.2.0/schema.json"
    core = "https://vecorel.org/specification/v0.1.0/schema.yaml"
    # all schemas are local, the core schema requires "id"
    schema_map = {}
    for name in ["id", *ORDERED_KEYS]:
        uri = core if name == "id" else f"https://example.com/{name}/v0.1.0/schema.yaml"
        path = Path(folder) / f"{name}.yaml"
        path.write_text(json.dumps({"$schema": sdl, "required": [name], "properties": {name: {}}}))
        schema_map[uri] = path
    half = len(ORDERED_KEYS) // 2
    a, b = ORDERED_KEYS[:half], ORDERED_KEYS[half:]
    collections = [
        Collection(
            {
                "schemas": {cid: list(schema_map)},
                "schemas:custom": {
                    "$schema": sdl,
                    # a merge only keeps what both require, in the order of the first
                    "required": required,
                    "properties": {
                        **{k: {"type": "string"} for k in keys},
                        "x": {"type": "string", **{f"x{k}": k for k in keys}},
                    },
                },
            }
        )
        for cid, keys, required in [
            ("c1", a, ORDERED_KEYS),
            ("c2", b, list(reversed(ORDERED_KEYS))),
        ]
    ]
    merged = merge_collections(collections)
    resolved = merged.get_schemas()["c1"].merge_schemas(schema_map=schema_map)
    return json.dumps(
        {"collection": merged, "required": resolved["required"]}, cls=VecorelJSONEncoder
    )


def test_merged_metadata_does_not_depend_on_the_hash_seed(tmp_path):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    script = (
        "import sys; from tests.test_ops import _merged_metadata; "
        "print(_merged_metadata(sys.argv[1]))"
    )
    results = []
    for seed in ["0", "1", "2", "3", "42"]:
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(root)}
        out = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path)],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        results.append(json.loads(out.strip().splitlines()[-1]))
    assert results == [results[0]] * len(results)

    custom = results[0]["collection"]["schemas:custom"]
    assert custom["required"] == ORDERED_KEYS
    assert list(custom["properties"]) == [*ORDERED_KEYS[:4], "x", *ORDERED_KEYS[4:]]
    assert list(custom["properties"]["x"]) == ["type", *[f"x{k}" for k in ORDERED_KEYS]]
    # in the order of the schema URIs
    assert results[0]["required"] == [*sorted(ORDERED_KEYS), "id"]
    schemas = results[0]["collection"]["schemas"]
    assert schemas["c1"] == sorted(schemas["c1"])


def test_sets_of_mixed_types_are_encoded_in_a_fixed_order():
    import json

    from vecorel_cli.encoding.geojson import VecorelJSONEncoder

    encoded = json.dumps({"b", 2, "a", 10, 1.5}, cls=VecorelJSONEncoder)
    # by type name, then by repr
    assert encoded == '[1.5, 10, 2, "a", "b"]'
