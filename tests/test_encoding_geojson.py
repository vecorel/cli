import json
from pathlib import Path

import pytest

from vecorel_cli.encoding.geojson import GeoJSON
from vecorel_cli.vecorel.collection import Collection


def test_init_paths(tmp_folder):
    fpath = str(tmp_folder / "test.json")
    ppath = Path(fpath)

    assert GeoJSON(fpath).uri == ppath
    assert GeoJSON(ppath).uri == ppath


def test_get_datatypes_uri():
    uri = GeoJSON.get_datatypes_uri("1.0.0")
    expected = "https://vecorel.org/specification/v1.0.0/geojson/datatypes.json"
    assert uri == expected


def test_get_format():
    assert GeoJSON("test.json").get_format() == "GeoJSON"


@pytest.mark.parametrize(
    "test",
    [
        ("tests/data-files/inspire.json", ["schemas", "schemas:custom"]),
        ("tests/data-files/inspire2.json", ["schemas"]),
    ],
)
def test_get_collection_exists(test):
    path, expected_keys = test
    geojson = GeoJSON(path)
    collection = geojson.get_collection()

    assert isinstance(collection, Collection)
    assert list(collection.keys()) == expected_keys
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


@pytest.mark.parametrize("bom", [False, True], ids=["without-bom", "with-bom"])
def test_read_geojson_decodes_utf8(tmp_folder, cp1252_locale, bom):
    feature = {
        "type": "Feature",
        "id": "1",
        "properties": {"name": "Grünland"},
        "geometry": {"type": "Point", "coordinates": [0, 0]},
    }
    file_path = tmp_folder / "umlaut.json"
    file_path.write_text(
        # ensure_ascii=False so the file really holds multi-byte UTF-8, not an escape sequence
        json.dumps({"type": "FeatureCollection", "features": [feature]}, ensure_ascii=False),
        encoding="utf-8-sig" if bom else "utf-8",
    )

    geojson = GeoJSON(file_path)

    assert geojson.read_geojson()["features"][0]["properties"]["name"] == "Grünland"
    # read(num=...) takes the streaming branch, which opens the file separately
    assert geojson.read(num=1)["name"].iloc[0] == "Grünland"
