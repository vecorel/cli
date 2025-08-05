from pathlib import Path

import pytest

from vecorel_cli.create_geoparquet import CreateGeoParquet
from vecorel_cli.encoding.geoparquet import GeoParquet


def test_create_geoparquet(tmp_parquet_file: Path):
    inputs = [
        "tests/data-files/inspire.json",
        "tests/data-files/inspire2.json",
    ]
    creator = CreateGeoParquet()
    creator.create(inputs, tmp_parquet_file)
    assert tmp_parquet_file.exists()

    gp = GeoParquet(tmp_parquet_file)

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


def test_create_geoparquet_invalid_file(tmp_folder):
    out = tmp_folder / "output.parquet"
    gp = CreateGeoParquet()
    with pytest.raises(ValueError):
        gp.create("invalid.parquet", out)
    with pytest.raises(FileNotFoundError):
        gp.create(["invalid.json"], out)
