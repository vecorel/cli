from pathlib import Path

import pytest

from vecorel_cli.encoding.geoparquet import GeoParquet
from vecorel_cli.merge import MergeDatasets


def test_merge(tmp_parquet_file: Path):
    files = [
        "tests/data-files/inspire.parquet",
        "tests/data-files/admin.json",
    ]

    crs = "EPSG:25832"

    merge = MergeDatasets()
    merge.merge(
        source=files,
        target=tmp_parquet_file,
        crs=crs,
        includes=["inspire:id", "admin:country_code", "admin:subdivision_code"],
        excludes=[],
    )

    gp = GeoParquet(tmp_parquet_file)

    collection = gp.get_collection()
    cids = list(collection.get("schemas", {}).keys())
    cids.sort()
    assert cids == ["de", "inspire"]

    data = gp.read()
    assert len(data) == 3
    assert data.crs == crs

    columns = list(gp.get_properties().keys())
    columns.sort()
    assert columns == [
        "admin:country_code",
        "admin:subdivision_code",
        "bbox",
        "collection",
        "geometry",
        "id",
        "inspire:id",
    ]


def test_merge_invalid_file(tmp_folder):
    out = tmp_folder / "output.parquet"
    merge = MergeDatasets()
    with pytest.raises(ValueError):
        merge.merge("invalid.parquet", out)
    with pytest.raises(FileNotFoundError):
        merge.merge(["invalid.parquet"], out)
