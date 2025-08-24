import pytest

from vecorel_cli.encoding.geoparquet import GeoParquet
from vecorel_cli.improve import ImproveData
from vecorel_cli.vecorel.extensions import GEOMETRY_METRICS

# todo: add test for fix-geometries and explode-geometries


def test_improve_compression(tmp_parquet_file):
    source = "tests/data-files/inspire.parquet"
    improve = ImproveData()
    improve.improve_file(source, tmp_parquet_file, compression="zstd")

    gp = GeoParquet(tmp_parquet_file)
    assert gp.get_compression() == "zstd"


def test_improve_rename(tmp_parquet_file):
    source = "tests/data-files/admin.json"
    improve = ImproveData()
    improve.improve_file(source, tmp_parquet_file, rename={"foo": "test"})

    gp = GeoParquet(tmp_parquet_file)
    props = gp.get_properties()
    assert "test" in props
    assert "foo" not in props


def test_improve_add_sizes(tmp_parquet_file):
    source = "tests/data-files/inspire.parquet"
    improve = ImproveData()
    improve.improve_file(source, tmp_parquet_file, add_sizes=True)

    gp = GeoParquet(tmp_parquet_file)

    props = gp.get_properties()
    assert "metrics:area" in props
    assert "metrics:perimeter" in props

    data = gp.read()
    assert all(data["metrics:area"] > 0)
    assert all(data["metrics:perimeter"] > 0)

    schemas = gp.get_collection().get_schemas()
    assert "inspire" in schemas
    assert GEOMETRY_METRICS in schemas["inspire"]


def test_improve_crs(tmp_parquet_file):
    source = "tests/data-files/inspire.parquet"
    improve = ImproveData()
    improve.improve_file(source, tmp_parquet_file, crs="EPSG:3857")

    gp = GeoParquet(tmp_parquet_file)
    data = gp.read()
    assert data.crs == "EPSG:3857"


def test_improve_invalid_file():
    improve = ImproveData()
    with pytest.raises(FileNotFoundError):
        improve.improve_file("invalid.parquet")
