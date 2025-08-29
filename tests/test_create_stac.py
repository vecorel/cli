from pathlib import Path

import pytest

from vecorel_cli.create_stac import CreateStacCollection
from vecorel_cli.registry import Registry
from vecorel_cli.vecorel.util import load_file

files = [("de-sh.parquet", "collection-parquet.json"), ("de-sh.json", "collection-json.json")]


@pytest.mark.parametrize("file, expected_file", files)
def test_create_stac_collection(tmp_folder: Path, file: str, expected_file: str):
    base = Path("tests/data-files/stac/")
    source = base / file
    expected_file = base / expected_file
    out_file = tmp_folder / "collection.json"

    gj = CreateStacCollection()
    gj.create_cli(source, out_file, temporal_property="determination_datetime", indent=2)

    assert out_file.exists()

    created_file = load_file(out_file)
    expected = load_file(expected_file)

    assert isinstance(created_file, dict), "Created file is not a valid JSON dict"

    # Cater for environment differences in paths
    assert "assets" in created_file
    assert "data" in created_file["assets"]
    assert "href" in created_file["assets"]["data"]
    del created_file["assets"]["data"]["href"]
    del expected["assets"]["data"]["href"]
    # Cater for floating point differences
    assert "extent" in created_file
    assert "spatial" in created_file["extent"]
    assert "bbox" in created_file["extent"]["spatial"]
    del created_file["extent"]["spatial"]["bbox"]
    del expected["extent"]["spatial"]["bbox"]
    # Cater for differences in version numbers
    assert "assets" in created_file
    assert "data" in created_file["assets"]
    assert "processing:software" in created_file["assets"]["data"]
    assert "vecorel-cli" in created_file["assets"]["data"]["processing:software"]
    assert (
        created_file["assets"]["data"]["processing:software"]["vecorel-cli"]
        == Registry.get_version()
    )
    del created_file["assets"]["data"]["processing:software"]["vecorel-cli"]
    del expected["assets"]["data"]["processing:software"]["vecorel-cli"]

    assert created_file == expected
