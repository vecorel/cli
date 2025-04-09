from vecorel_cli.jsonschema import jsonschema
from vecorel_cli.util import load_file
from vecorel_cli.version import vecorel_version


def test_conversion():
    config = {
        "schema": "tests/data-files/jsonschema/test1.yaml",
        "vecorel_version": vecorel_version,
        "id": "https://example.com/schema.json",
    }
    created_json_schema = jsonschema(config)

    expected_json_schema = load_file("tests/data-files/jsonschema/test1.json")
    assert created_json_schema == expected_json_schema
