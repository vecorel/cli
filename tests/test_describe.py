import sys

from loguru import logger

from vecorel_cli.describe import DescribeFile


def test_describe_geoparquet(capsys):
    # todo: use fixture
    logger.remove()
    logger.add(sys.stdout, format="{message}", level="DEBUG", colorize=False)

    path = "tests/data-files/inspire.parquet"
    describe = DescribeFile(path)
    describe.describe()

    out, err = capsys.readouterr()

    assert "Format: GeoParquet, version 1.1.0" in out
    assert "- https://fiboa.github.io/inspire-extension/v0.2.0/schema.yaml" in out
    assert "Columns: 8" in out
    assert "Rows: 2" in out
    assert "Row Groups: 1" in out
    assert "Version: 0.1.0" in out
    assert "https://fiboa.github.io/inspire-extension/v0.2.0/schema.yaml" in out

    assert "geometry: binary" in out
    assert "inspire:id: string" in out
    assert "collection: string" in out
    assert "id: string" in out
    assert "bbox: struct<xmin: double, ymin: double, xmax: double, ymax: double>" in out

    assert "determination_datetime: 2020-01-01T00:00:00Z" in out
    assert "collection: inspire" in out

    assert "6467974" in out
    assert "6467975" in out


def test_describe_geojson(capsys):
    # todo: use fixture
    logger.remove()
    logger.add(sys.stdout, format="{message}", level="DEBUG", colorize=False)

    path = "tests/data-files/inspire.json"
    describe = DescribeFile(path)
    describe.describe()

    out, err = capsys.readouterr()

    assert "Format: GeoJSON" in out
    assert "Version: 0.1.0" in out
    assert "https://fiboa.github.io/inspire-extension/v0.2.0/schema.yaml" in out
    assert "File format is not columnar" in out
    assert "No collection metadata found" in out
    assert "6467974" in out
