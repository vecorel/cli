import tempfile
from pathlib import Path

from pytest import fixture

from vecorel_cli.create_geojson import CreateGeoJson
from vecorel_cli.vecorel.util import load_file


@fixture(autouse=True)
def out_folder():
    # Windows can't properly handle NamedTemporaryFile etc.
    # Let's create a folder instead and then create a file manually.
    with tempfile.TemporaryDirectory() as temp_dir:
        folder = Path(temp_dir)
        yield folder


def test_create_geojson_featurecollection(out_folder: Path):
    source = "tests/data-files/inspire.parquet"
    out_file = out_folder / "inspire.json"

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


def test_create_geojson_features(out_folder: Path):
    source = "tests/data-files/inspire.parquet"

    gj = CreateGeoJson()
    gj.create(source, out_folder, split=True)

    def check_file(id_):
        out_file = out_folder / f"{id_}.json"
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
