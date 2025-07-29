import pytest
from click.testing import CliRunner

from vecorel_cli import validate


@pytest.mark.skip(reason="not implemented yet")
def test_validate():
    path = "tests/data-files/inspire.parquet"
    runner = CliRunner()
    result = runner.invoke(validate, [path, "--data"])
    assert result.exit_code == 0, result.output
    assert "Validating tests/data-files/inspire.parquet" in result.output
    assert "- https://fiboa.github.io/inspire-extension/v0.2.0/schema.yaml" in result.output
    assert "Data was not validated" not in result.output
    assert "=> VALID" in result.output
