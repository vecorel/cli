from vecorel_cli.create_jsonschema import CreateJsonSchema
from vecorel_cli.encoding.geojson import GeoJSON
from vecorel_cli.vecorel.util import load_file
from vecorel_cli.vecorel.version import vecorel_version


def test_conversion():
    cmd = CreateJsonSchema()
    created_json_schema = cmd.create_from_files(
        schema_uri="tests/data-files/jsonschema/test1.yaml",
        datatypes_uri=GeoJSON.datatypes_schema_uri.format(version=vecorel_version),
        schema_id="https://example.com/schema.json",
    )
    expected_json_schema = load_file("tests/data-files/jsonschema/test1.json")
    assert created_json_schema == expected_json_schema
