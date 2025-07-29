import re

import pytest
from click.testing import CliRunner
from pytest import mark

from vecorel_cli import convert, validate

"""
Create input files with: `ogr2ogr output.gpkg -limit 100 input.gpkg`
"""

tests = []
test_path = "tests/data-files/convert"
extra_convert_parameters = {}


@pytest.mark.skip(reason="not implemented yet")
@mark.parametrize("converter", tests)
def test_converter(tmp_file, converter, block_stream_file):
    path = f"tests/data-files/convert/{converter}"
    runner = CliRunner()
    args = [converter, "-o", tmp_file.name, "-c", path] + extra_convert_parameters.get(
        converter, []
    )
    result = runner.invoke(convert, args)
    assert result.exit_code == 0, result.output
    error = re.search("Skipped - |No schema defined", result.output)
    if error:
        raise AssertionError(f"Found error in output: '{error.group(0)}'\n\n{result.output}")

    result = runner.invoke(validate, [tmp_file.name, "--data"])
    assert result.exit_code == 0, result.output
