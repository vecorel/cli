from vecorel_cli.create_jsonschema import CreateJsonSchema
from vecorel_cli.encoding.geojson import GeoJSON
from vecorel_cli.validate_schema import ValidateSchema
from vecorel_cli.vecorel.util import load_file
from vecorel_cli.vecorel.version import vecorel_version

vecorel_schema_uri = "tests/data-files/jsonschema/schema.yaml"
vecorel_schema = load_file(vecorel_schema_uri)
datatypes_uri = GeoJSON.get_datatypes_uri(vecorel_version)
datatypes = GeoJSON.load_datatypes(datatypes_uri)
schema_id = "https://example.com/schema.json"
point = {"type": "Point", "coordinates": [0, 0]}
schemas = {"test_collection": ["https://vecorel.org/specification/v0.1.0/schema.yaml"]}


def check(obj):
    cmd = CreateJsonSchema()
    jsonschema = cmd.create_from_dict(vecorel_schema, datatypes, schema_id)
    validator = ValidateSchema(jsonschema)
    return validator.validate(obj)


def test_conversion():
    cmd = CreateJsonSchema()
    created_json_schema = cmd.create_from_file(
        schema_uri=vecorel_schema_uri,
        datatypes_uri=datatypes_uri,
        schema_id=schema_id,
    )
    expected_json_schema = load_file("tests/data-files/jsonschema/schema.json")
    assert created_json_schema == expected_json_schema


def test_valid_featurecollection():
    result = check(
        {
            "schemas": schemas,
            "collection": "test",
            "type": "FeatureCollection",
            "features": [
                {"id": "1", "type": "Feature", "properties": {"area": 1234}, "geometry": point}
            ],
        }
    )
    assert result == []


def test_valid_feature():
    result = check(
        {
            "schemas": schemas,
            "id": "1",
            "type": "Feature",
            "properties": {"collection": "test_collection"},
            "geometry": point,
        }
    )
    assert result == []


def test_no_duplicate_collection():
    result = check(
        {
            "schemas": schemas,
            "collection": "test_collection",
            "type": "FeatureCollection",
            "features": [
                {
                    "id": "1",
                    "type": "Feature",
                    "properties": {"collection": "test_collection"},
                    "geometry": point,
                }
            ],
        }
    )
    assert len(result) > 0
    assert result[0].message.endswith(
        "is valid under each of {'type': 'object', 'properties': {'features': {'type': 'array', 'items': {'type': 'object', 'properties': {'properties': {'required': ['collection']}}}}}}, {'required': ['collection']}"
    )


def test_no_schemas_in_props():
    result = check(
        {
            "id": "1",
            "type": "Feature",
            "properties": {"schemas": schemas, "collection": "test_collection"},
            "geometry": point,
        }
    )
    assert len(result) > 0
    assert result[0].message == "'schemas' is a required property"


def test_no_id_in_props():
    result = check(
        {
            "schemas": schemas,
            "type": "Feature",
            "properties": {"id": "1", "collection": "test_collection"},
            "geometry": point,
        }
    )
    assert len(result) > 0
    assert result[0].message == "'id' is a required property"


def test_invalid_prop_in_prop():
    result = check(
        {
            "schemas": schemas,
            "id": "1",
            "type": "Feature",
            "properties": {
                "collection": "test_collection",
                "determination_datetime": 123,
            },
            "geometry": point,
        }
    )
    assert len(result) > 0
    assert result[0].message == "123 is not of type 'string'"


def test_invalid_prop_in_root():
    result = check(
        {
            "schemas": schemas,
            "id": "",
            "type": "Feature",
            "properties": {"collection": "test_collection"},
            "geometry": point,
        }
    )
    assert len(result) > 0
    assert result[0].message == "'' should be non-empty"
