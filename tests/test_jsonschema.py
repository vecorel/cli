from vecorel_cli.const import VECOREL_GEOJSON_DATATYPES_SCHEMA
from vecorel_cli.create_jsonschema import CreateJsonSchema
from vecorel_cli.util import load_file
from vecorel_cli.version import vecorel_version


def test_conversion():
    cmd = CreateJsonSchema()
    created_json_schema = cmd.create_from_files(
        schema_uri="tests/data-files/jsonschema/test1.yaml",
        datatypes_uri=VECOREL_GEOJSON_DATATYPES_SCHEMA.format(version=vecorel_version),
        schema_id="https://example.com/schema.json",
    )
    expected_json_schema = load_file("tests/data-files/jsonschema/test1.json")
    assert created_json_schema == expected_json_schema
