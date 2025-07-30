import tempfile
from pathlib import Path

from pytest import fixture

from vecorel_cli.create_geoparquet import CreateGeoParquet
from vecorel_cli.encoding.geoparquet import GeoParquet


@fixture(autouse=True)
def out_file():
    # Windows can't properly handle NamedTemporaryFile etc.
    # Let's create a folder instead and then create a file manually.
    with tempfile.TemporaryDirectory() as temp_dir:
        folder = Path(temp_dir)
        file = folder / "test.parquet"

        yield file


def test_create_geoparquet(out_file: Path):
    inputs = [
        "tests/data-files/inspire.json",
        "tests/data-files/inspire2.json",
    ]
    creator = CreateGeoParquet()
    creator.create(inputs, out_file)
    assert out_file.exists()

    gp = GeoParquet(out_file)

    collection = gp.get_collection()
    assert "schemas" in collection
    schema_ids = collection["schemas"].keys()
    assert len(schema_ids) == 1
    assert "inspire" in schema_ids

    data = gp.read()
    assert len(data) == 2
    assert data.iloc[0]["id"] == "6467974"
    assert data.iloc[1]["id"] == "6467975"
    assert data.iloc[0]["collection"] == "inspire"
    assert data.iloc[1]["collection"] == "inspire"
