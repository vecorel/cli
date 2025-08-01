from vecorel_cli.encoding.geoparquet import GeoParquet
from vecorel_cli.improve import ImproveData

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
    assert "area" in props
    assert "perimeter" in props

    data = gp.read()
    assert all(data["area"] > 0)
    assert all(data["perimeter"] > 0)


def test_improve_crs(tmp_parquet_file):
    source = "tests/data-files/inspire.parquet"
    improve = ImproveData()
    improve.improve_file(source, tmp_parquet_file, crs="EPSG:3857")

    gp = GeoParquet(tmp_parquet_file)
    data = gp.read()
    assert data.crs == "EPSG:3857"
