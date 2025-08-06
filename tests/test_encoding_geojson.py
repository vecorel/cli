from pathlib import Path

from vecorel_cli.encoding.geojson import GeoJSON
from vecorel_cli.vecorel.collection import Collection


def test_init_paths(tmp_folder):
    fpath = str(tmp_folder / "test.json")
    ppath = Path(fpath)

    assert GeoJSON(fpath).file == ppath
    assert GeoJSON(ppath).file == ppath


def test_get_datatypes_uri():
    uri = GeoJSON.get_datatypes_uri("1.0.0")
    expected = "https://vecorel.github.io/specification/v1.0.0/geojson/datatypes.json"
    assert uri == expected


def test_get_format():
    assert GeoJSON("test.json").get_format() == "GeoJSON"


def test_get_collection_exists():
    geojson = GeoJSON("tests/data-files/inspire.json")

    collection = geojson.get_collection()

    assert isinstance(collection, Collection)
    assert list(collection.keys()) == ["schemas"]
    assert "inspire" in collection["schemas"]


def test_get_collection_does_not_exist():
    collection = GeoJSON("invalid.json").get_collection()
    assert collection == Collection()


def test_get_collection_returns_existing(tmp_folder):
    file_path = tmp_folder / "test.json"
    geojson = GeoJSON(file_path)

    expected = Collection({"test": "data"})
    geojson.collection = expected

    result = geojson.get_collection()
    assert result == expected
