import sys

import pytest
from loguru import logger

from vecorel_cli.describe import DescribeFile

tests = [
    ("tests/data-files/inspire.parquet", {}),
    ("tests/data-files/inspire.parquet", {"num": 0}),
    ("tests/data-files/inspire.parquet", {"num": 1}),
]


@pytest.mark.parametrize("test", tests)
def test_describe_geoparquet(capsys, test):
    path, kwargs = test
    # todo: use fixture
    logger.remove()
    logger.add(sys.stdout, format="{message}", level="DEBUG", colorize=False)

    describe = DescribeFile(path)
    describe.describe(**kwargs)

    out, err = capsys.readouterr()

    assert "Format: GeoParquet, version 1.1.0" in out
    assert "- https://fiboa.github.io/inspire-extension/v0.3.0/schema.yaml" in out
    assert "Columns: 8" in out
    assert "Rows: 2" in out
    assert "Row Groups: 1" in out
    assert "Version: 0.1.0" in out

    assert "geometry: binary" in out
    assert "inspire:id: string" in out
    assert "collection: string" in out
    assert "id: string" in out
    assert "bbox: struct<xmin: double, ymin: double, xmax: double, ymax: double>" in out

    assert "determination_datetime: 2020-01-01T00:00:00Z" in out
    assert "collection: inspire" in out

    num = kwargs.get("num", 10)
    if num == 0:
        assert "Omitted" in out
    if num == 1:
        assert "6467974" in out
        assert "6467975" not in out
    if num > 1:
        assert "6467974" in out
        assert "6467975" in out


@pytest.mark.parametrize(
    "test",
    [
        (
            "tests/data-files/inspire.json",
            True,
            ["6467974", "schemas:custom:", "Custom Schemas: Yes"],
        ),
        (
            "tests/data-files/inspire2.json",
            False,
            ["6467975", "Nothing found", "Custom Schemas: No"],
        ),
    ],
)
def test_describe_geojson(capsys, test):
    # todo: use fixture
    logger.remove()
    logger.add(sys.stdout, format="{message}", level="DEBUG", colorize=False)

    path, verbose, matches = test
    describe = DescribeFile(path)
    describe.describe(verbose=verbose)

    out, err = capsys.readouterr()

    assert "Format: GeoJSON" in out
    assert "Version: 0.1.0" in out
    assert "https://fiboa.github.io/inspire-extension/v0.3.0/schema.yaml" in out
    assert "File format is not columnar" in out
    for match in matches:
        assert match in out


def test_describe_invalid_file():
    with pytest.raises(FileNotFoundError):
        describe = DescribeFile("invalid.json")
        describe.describe()
