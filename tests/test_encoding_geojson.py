from pathlib import Path

from vecorel_cli.encoding.geojson import GeoJSON


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

    assert isinstance(collection, dict)
    assert list(collection.keys()) == ["schemas"]
    assert "inspire" in collection["schemas"]


def test_get_collection_does_not_exist():
    collection = GeoJSON("invalid.json").get_collection()
    assert collection == {}


def test_get_collection_returns_existing(tmp_folder):
    file_path = tmp_folder / "test.json"
    geojson = GeoJSON(file_path)

    test_collection = {"test": "data"}
    geojson.collection = test_collection

    result = geojson.get_collection()
    assert result == test_collection
