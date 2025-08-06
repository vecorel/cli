from jsonschema.exceptions import ValidationError

from vecorel_cli.validate_schema import ValidateSchema


def test_validate_schema_valid():
    path = "tests/data-files/sdl/inspire-schema.yaml"
    cmd = ValidateSchema()
    result = cmd.validate_file(path)
    assert isinstance(result, list)
    assert len(result) == 0


def test_validate_schema_invalid():
    path = "tests/data-files/sdl/inspire-schema-invalid.yaml"
    cmd = ValidateSchema()
    result = cmd.validate_file(path)
    assert isinstance(result, list)
    assert len(result) == 1
    error = result[0]
    assert isinstance(error, ValidationError)
    assert error.message.startswith("'STRING' is not one of [")
