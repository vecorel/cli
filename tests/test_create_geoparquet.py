import tempfile
from pathlib import Path

from pytest import fixture

from vecorel_cli.create_geoparquet import CreateGeoParquet
from vecorel_cli.encoding.geoparquet import GeoParquet


@fixture(autouse=True)
def out_file():
    # Windows can't properly handle NamedTemporaryFile etc.
    # Let's create a folder instead and then create a file manually.
    with tempfile.TemporaryDirectory(delete=False) as temp_dir:
        folder = Path(temp_dir)
        file = folder / "test.parquet"
        yield file

    # folder.unlink(missing_ok=True)


def test_create_geoparquet(out_file):
    path = "tests/data-files/inspire.json"
    creator = CreateGeoParquet()
    creator.create(path, out_file)
    assert out_file.exists()

    gp = GeoParquet(out_file)
    data = gp.read()
    assert len(data) == 1
    assert data.iloc[0]["name"] == "Test Area"
