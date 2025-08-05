from pathlib import Path

import pytest

from vecorel_cli.create_geojson import CreateGeoJson
from vecorel_cli.vecorel.util import load_file


def test_create_geojson_featurecollection(tmp_folder: Path):
    source = "tests/data-files/inspire.parquet"
    out_file = tmp_folder / "inspire.json"

    gj = CreateGeoJson()
    gj.create(source, out_file, split=False)

    assert out_file.exists()

    geojson = load_file(out_file)
    assert geojson.get("type") == "FeatureCollection"
    assert len(geojson.get("features", [])) == 2

    def checks(features, id):
        assert any(feature.get("id") == id for feature in features)
        assert any(
            feature.get("properties", {}).get("inspire:id")
            == "https://geodaten.nrw.de/id/inspire-lc-dgl/landcoverunit/6467974"
            for feature in features
        )

    checks(geojson.get("features", []), "6467974")
    checks(geojson.get("features", []), "6467975")


def test_create_geojson_features(tmp_folder: Path):
    source = "tests/data-files/inspire.parquet"

    gj = CreateGeoJson()
    gj.create(source, tmp_folder, split=True)

    def check_file(id_):
        out_file = tmp_folder / f"{id_}.json"
        assert out_file.exists()

        geojson = load_file(out_file)
        assert geojson.get("type") == "Feature"
        assert geojson.get("id") == id_
        assert (
            geojson.get("properties", {}).get("inspire:id")
            == f"https://geodaten.nrw.de/id/inspire-lc-dgl/landcoverunit/{id_}"
        )

        assert isinstance(geojson.get("schemas"), dict)
        assert isinstance(geojson.get("schemas").get("inspire"), list)

    check_file("6467974")
    check_file("6467975")


def test_create_geojson_invalid_file(tmp_folder):
    gj = CreateGeoJson()
    with pytest.raises(FileNotFoundError):
        gj.create("invalid.parquet", tmp_folder)
