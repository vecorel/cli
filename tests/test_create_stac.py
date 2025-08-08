from pathlib import Path

from vecorel_cli.create_stac import CreateStacCollection
from vecorel_cli.vecorel.util import load_file


def test_create_stac_collection(tmp_folder: Path):
    source = Path("tests/data-files/stac/de-sh.parquet")
    expected_file = "tests/data-files/stac/collection.json"
    out_file = tmp_folder / "collection.json"

    gj = CreateStacCollection()
    gj.create_cli(source, out_file, temporal_property="determination_datetime", indent=2)

    assert out_file.exists()

    created_file = load_file(out_file)
    expected = load_file(expected_file)

    assert isinstance(created_file, dict), "Created file is not a valid JSON dict"

    # Cater for environment differences in paths
    del expected["assets"]["data"]["href"]
    assert "assets" in created_file
    assert "data" in created_file["assets"]
    assert "href" in created_file["assets"]["data"]
    del created_file["assets"]["data"]["href"]
    # Cater for floating point differences
    del expected["extent"]["spatial"]["bbox"]
    assert "extent" in created_file
    assert "spatial" in created_file["extent"]
    assert "bbox" in created_file["extent"]["spatial"]
    del created_file["extent"]["spatial"]["bbox"]

    assert created_file == expected
