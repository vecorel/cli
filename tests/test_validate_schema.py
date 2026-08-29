from click.testing import CliRunner
from jsonschema.exceptions import ValidationError

from vecorel_cli.validate_schema import ValidateSchema


def get_cli_command():
    cmd = ValidateSchema.get_cli_command(ValidateSchema)
    for arg in ValidateSchema.get_cli_args().values():
        cmd = arg(cmd)
    return cmd


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


def test_validate_schema_cli_valid_exit_code():
    result = CliRunner().invoke(get_cli_command(), ["tests/data-files/sdl/inspire-schema.yaml"])
    assert result.exit_code == 0


def test_validate_schema_cli_invalid_exit_code():
    result = CliRunner().invoke(
        get_cli_command(), ["tests/data-files/sdl/inspire-schema-invalid.yaml"]
    )
    assert result.exit_code != 0
