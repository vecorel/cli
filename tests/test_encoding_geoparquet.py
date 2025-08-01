from pathlib import Path

from vecorel_cli.encoding.geoparquet import GeoParquet


def test_init_paths(tmp_folder):
    fpath = str(tmp_folder / "test.parquet")
    ppath = Path(fpath)

    assert GeoParquet(fpath).file == ppath
    assert GeoParquet(ppath).file == ppath


def test_get_format():
    assert (
        GeoParquet("tests/data-files/inspire.parquet").get_format() == "GeoParquet, version 1.1.0"
    )


def test_get_collection_exists():
    geojson = GeoParquet("tests/data-files/inspire.parquet")

    collection = geojson.get_collection()

    assert isinstance(collection, dict)
    fields = list(collection.keys())
    fields.sort()
    assert fields == ["collection", "determination_datetime", "schemas"]
    assert "inspire" in collection["schemas"]


def test_get_collection_does_not_exist():
    collection = GeoParquet("invalid.parquet").get_collection()
    assert collection == {}


def test_get_collection_returns_existing(tmp_folder):
    file_path = tmp_folder / "test.parquet"
    geojson = GeoParquet(file_path)

    test_collection = {"test": "data"}
    geojson.collection = test_collection

    result = geojson.get_collection()
    assert result == test_collection
