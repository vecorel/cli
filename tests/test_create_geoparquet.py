import os
import tempfile

import pytest
from click.testing import CliRunner
from pytest import fixture

from vecorel_cli import create_geoparquet, validate
from vecorel_cli.encoding.geoparquet import GeoParquet


@fixture
def out_file():
    with tempfile.NamedTemporaryFile() as out:
        yield out.name


@pytest.mark.skip(reason="not implemented yet")
def test_create_geoparquet(out_file):
    path = "tests/data-files/inspire.json"
    runner = CliRunner()
    result = runner.invoke(create_geoparquet, [path, "-o", out_file])
    assert result.exit_code == 0, result.output
    assert f"Wrote to {out_file}" in result.output

    assert os.path.exists(out_file)
    result = runner.invoke(validate, [out_file, "--data"])
    assert result.exit_code == 0, result.output

    gp = GeoParquet(out_file)
    data = gp.read()
    assert len(data) == 1
