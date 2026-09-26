import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely
from loguru import logger

from vecorel_cli.cli.logger import LoggerMixin
from vecorel_cli.encoding.geoparquet import GeoParquet
from vecorel_cli.merge import MergeDatasets
from vecorel_cli.validate import ValidateData
from vecorel_cli.vecorel.schemas import Schemas

CORE = Schemas.get_core_uri()
ADMIN = "https://vecorel.org/administrative-division-extension/v0.1.0/schema.yaml"
ENGINES = ["duckdb", "geopandas"]


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


def _part(
    folder,
    name,
    cid,
    n,
    ids=None,
    columns=None,
    collection=None,
    schemas=None,
    custom=None,
    with_collection=True,
    geoparquet_version=None,
    crs="EPSG:4326",
):
    """A part with n rows; only the given collection-level values are in its collection."""
    gdf = gpd.GeoDataFrame(
        {
            "id": ids or [f"{name}{i}" for i in range(n)],
            **(columns or {}),
            "geometry": [shapely.box(i, 0, i + 1, 1) for i in range(n)],
        },
        crs="EPSG:4326",
    ).to_crs(crs)
    path = folder / f"{name}.parquet"
    meta = {"schemas": {cid: schemas or [CORE]}, **(collection or {})}
    if with_collection:
        meta["collection"] = cid
    if custom:
        meta["schemas:custom"] = custom
    gp = GeoParquet(path)
    gp.set_collection(meta)
    gp.write(gdf, dehydrate=False, geoparquet_version=geoparquet_version)
    return path


def _with_nullable_column(path, name, values):
    """Rewrites a column as nullable with the given values, as other tools could write it."""
    table = pq.read_table(path)
    metadata = table.schema.metadata
    index = table.schema.get_field_index(name)
    if index >= 0:
        table = table.remove_column(index)
    table = table.append_column(pa.field(name, pa.string()), pa.array(values, pa.string()))
    pq.write_table(table.replace_schema_metadata(metadata), path)
    return path


def _merge(folder, parts, engine="auto", **kwargs):
    out = folder / f"merged-{engine}.parquet"
    MergeDatasets().merge(source=[str(p) for p in parts], target=out, engine=engine, **kwargs)
    return out


def _read(path):
    table = pq.read_table(path)
    collection = json.loads(table.schema.metadata[b"collection"])
    rows = table.drop_columns(["geometry"]).to_pylist()
    rows.sort(key=lambda row: (row.get("collection") or "", row["id"]))
    return rows, collection


def _errors(path):
    return ValidateData().validate(path, num=100, schema_map={}).errors


@pytest.fixture
def log():
    # capsys only captures during the test call, so collect the messages in a list,
    # after the first LoggerMixin has replaced the sinks
    LoggerMixin()
    messages = []
    logger.remove()
    logger.add(messages.append, format="{message}", level="DEBUG", colorize=False)

    def read():
        out = "".join(messages)
        messages.clear()
        return out

    yield read
    logger.remove()
    logger.add(sys.stdout, format="{message}", level="DEBUG", colorize=False)


@pytest.mark.parametrize("engine", ENGINES)
def test_merge_hydrates_array_and_object_constants(tmp_folder, engine):
    custom = {
        "properties": {
            "tags": {"type": "array", "items": {"type": "string"}},
            "attrs": {"type": "object", "properties": {"k": {"type": "string"}}},
        }
    }
    a = _part(
        tmp_folder, "a", "a", 2, collection={"tags": ["p", "q"], "attrs": {"k": "v"}}, custom=custom
    )
    b = _part(
        tmp_folder, "b", "b", 3, collection={"tags": ["r", "s"], "attrs": {"k": "w"}}, custom=custom
    )
    out = _merge(tmp_folder, [a, b], engine)

    rows, _ = _read(out)
    assert [(r["collection"], r["tags"], r["attrs"]) for r in rows] == [
        ("a", ["p", "q"], {"k": "v"}),
        ("a", ["p", "q"], {"k": "v"}),
        ("b", ["r", "s"], {"k": "w"}),
        ("b", ["r", "s"], {"k": "w"}),
        ("b", ["r", "s"], {"k": "w"}),
    ]
    assert _errors(out) == []


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("with_schema", [False, True])
def test_merge_keeps_shared_array_constants_in_the_collection(tmp_folder, engine, with_schema):
    custom = {"properties": {"tags": {"type": "array", "items": {"type": "string"}}}}
    custom = custom if with_schema else None
    a = _part(tmp_folder, "a", "a", 2, collection={"tags": ["x", "y"]}, custom=custom)
    b = _part(tmp_folder, "b", "b", 2, collection={"tags": ["x", "y"]}, custom=custom)
    out = _merge(tmp_folder, [a, b], engine)

    rows, collection = _read(out)
    assert collection["tags"] == ["x", "y"]
    assert all("tags" not in row for row in rows)


@pytest.mark.parametrize("engine", ENGINES)
def test_merge_hydrates_date_time_constants(tmp_folder, engine):
    custom = {"properties": {"dt": {"type": "date-time"}}}
    a = _part(tmp_folder, "a", "a", 2, collection={"dt": "2020-01-01T00:00:00Z"}, custom=custom)
    dts = pd.to_datetime(["2021-01-01T00:00:00Z", "2021-06-01T00:00:00Z"])
    b = _part(tmp_folder, "b", "b", 2, columns={"dt": dts}, custom=custom)
    out = _merge(tmp_folder, [a, b], engine)

    assert str(pq.read_schema(out).field("dt").type) == "timestamp[ms, tz=UTC]"
    rows, _ = _read(out)
    assert [r["dt"].isoformat() for r in rows] == [
        "2020-01-01T00:00:00+00:00",
        "2020-01-01T00:00:00+00:00",
        "2021-01-01T00:00:00+00:00",
        "2021-06-01T00:00:00+00:00",
    ]
    assert _errors(out) == []


@pytest.mark.parametrize("engine", ENGINES)
def test_merge_keeps_ids_that_repeat_in_other_collections(tmp_folder, engine, log):
    a = _part(tmp_folder, "a", "a", 2, ids=["1", "2"])
    b = _part(tmp_folder, "b", "b", 2, ids=["1", "2"])
    c = _part(tmp_folder, "c", "b", 1, ids=["1"])
    out = _merge(tmp_folder, [a, b, c], engine)

    rows, _ = _read(out)
    assert [(r["collection"], r["id"]) for r in rows] == [
        ("a", "1"),
        ("a", "2"),
        ("b", "1"),
        ("b", "1"),
        ("b", "2"),
    ]
    assert "repeat an id within their collection" in log()


@pytest.mark.parametrize("engine", ENGINES)
def test_merge_unites_the_schemas_of_a_collection(tmp_folder, engine):
    a = _part(tmp_folder, "a", "same", 2, columns={"admin:country_code": ["DE", "DE"]})
    b = _part(
        tmp_folder,
        "b",
        "same",
        2,
        columns={"admin:country_code": ["FR", "FR"]},
        schemas=[CORE, ADMIN],
    )
    out = _merge(tmp_folder, [b, a], engine)

    _, collection = _read(out)
    assert sorted(collection["schemas"]["same"]) == sorted([CORE, ADMIN])
    assert _errors(out) == []


@pytest.mark.parametrize("engine", ENGINES)
def test_merge_warns_about_collection_only_properties_that_differ(tmp_folder, engine, log):
    custom = {
        "properties": {"producer": {"type": "string"}, "source": {"type": "string"}},
        "collection": {"producer": True},
    }
    a = _part(
        tmp_folder, "a", "a", 2, collection={"producer": "Alice", "source": "x"}, custom=custom
    )
    b = _part(tmp_folder, "b", "b", 2, collection={"producer": "Bob", "source": "x"}, custom=custom)
    out = _merge(tmp_folder, [a, b], engine)

    rows, collection = _read(out)
    assert "producer" not in collection
    assert collection["source"] == "x"
    assert all("producer" not in row for row in rows)
    assert (
        "Collection-only properties differ between the datasets and are removed: producer" in log()
    )


@pytest.mark.parametrize("engine", ENGINES)
def test_merge_keeps_all_properties_by_default(tmp_folder, engine):
    custom = {"properties": {"name": {"type": "string"}}}
    a = _part(
        tmp_folder,
        "a",
        "a",
        2,
        columns={"admin:country_code": ["DE", "DE"], "name": ["x", "y"]},
        schemas=[CORE, ADMIN],
        custom=custom,
    )
    b = _part(tmp_folder, "b", "b", 2, columns={"name": ["z", "w"]}, custom=custom)
    out = _merge(tmp_folder, [a, b], engine)

    rows, _ = _read(out)
    assert [(r["admin:country_code"], r["name"]) for r in rows] == [
        ("DE", "x"),
        ("DE", "y"),
        (None, "z"),
        (None, "w"),
    ]
    # admin:country_code is only required in collection a
    assert _errors(out) == []

    out = _merge(tmp_folder, [a, b], engine, excludes=["name"])
    assert "name" not in pq.read_schema(out).names
    assert "admin:country_code" in pq.read_schema(out).names


@pytest.mark.parametrize("engine", ENGINES)
def test_merge_warns_when_includes_drop_required_properties(tmp_folder, engine, log):
    a = _part(
        tmp_folder, "a", "a", 2, columns={"admin:country_code": ["DE", "DE"]}, schemas=[CORE, ADMIN]
    )
    b = _part(
        tmp_folder, "b", "b", 2, columns={"admin:country_code": ["FR", "FR"]}, schemas=[CORE, ADMIN]
    )
    _merge(tmp_folder, [a, b], engine, includes=["foo"])
    assert (
        "Required properties are not included, the merged file will be invalid: admin:country_code"
        in log()
    )


@pytest.mark.parametrize("engine", ENGINES)
def test_merge_fills_a_missing_collection(tmp_folder, engine):
    a = _part(tmp_folder, "a", "a", 2, with_collection=False)
    b = _part(tmp_folder, "b", "b", 2)
    out = _merge(tmp_folder, [a, b], engine)

    rows, _ = _read(out)
    assert [r["collection"] for r in rows] == ["a", "a", "b", "b"]
    assert _errors(out) == []


@pytest.mark.parametrize("engine", ENGINES)
def test_merge_fills_missing_collection_values(tmp_folder, engine):
    a = _with_nullable_column(_part(tmp_folder, "a", "a", 2), "collection", ["a", None])
    b = _part(tmp_folder, "b", "b", 2)
    out = _merge(tmp_folder, [a, b], engine)

    rows, _ = _read(out)
    assert [r["collection"] for r in rows] == ["a", "a", "b", "b"]
    assert _errors(out) == []


@pytest.mark.parametrize("engine", ENGINES)
def test_merge_excludes_the_collection(tmp_folder, engine, log):
    a = _part(tmp_folder, "a", "a", 2)
    b = _part(tmp_folder, "b", "b", 2)
    out = _merge(tmp_folder, [a, b], engine, excludes=["collection"])

    assert "collection" not in pq.read_schema(out).names
    assert "the merged file will be invalid: collection" in log()


@pytest.mark.parametrize("engine", ENGINES)
def test_merge_keeps_rows_without_a_required_value(tmp_folder, engine):
    a = _part(
        tmp_folder, "a", "a", 2, columns={"admin:country_code": ["DE", "DE"]}, schemas=[CORE, ADMIN]
    )
    a = _with_nullable_column(a, "admin:country_code", ["DE", None])
    b = _part(
        tmp_folder, "b", "b", 2, columns={"admin:country_code": ["FR", "FR"]}, schemas=[CORE, ADMIN]
    )
    out = _merge(tmp_folder, [a, b], engine)

    rows, _ = _read(out)
    assert [r["admin:country_code"] for r in rows] == ["DE", None, "FR", "FR"]


@pytest.mark.parametrize("engine", ENGINES)
def test_merge_keeps_empty_geometries(tmp_folder, engine):
    a = _part(tmp_folder, "a", "a", 2)
    b = _part(tmp_folder, "b", "b", 2)
    gp = GeoParquet(b)
    gdf = gp.read()
    gdf.loc[0, "geometry"] = shapely.Polygon()
    gp.write(gdf, dehydrate=False)
    out = _merge(tmp_folder, [a, b], engine)

    assert pq.read_metadata(out).num_rows == 4


def test_merge_ignores_null_ids_for_duplicates(tmp_folder, log):
    a = _with_nullable_column(_part(tmp_folder, "a", "a", 2), "id", [None, None])
    b = _part(tmp_folder, "b", "b", 2)
    _merge(tmp_folder, [a, b], "geopandas")
    assert "repeat an id" not in log()


def test_merge_recomputes_the_bbox_of_geoparquet_1_0_parts(tmp_folder):
    a = _part(tmp_folder, "a", "a", 2, geoparquet_version="1.0.0")
    b = _part(tmp_folder, "b", "b", 2)
    out = _merge(tmp_folder, [a, b], "duckdb")

    bboxes = pq.read_table(out, columns=["bbox"]).column("bbox").to_pylist()
    assert len(bboxes) == 4 and None not in bboxes


def test_merge_engine_selection(tmp_folder, log):
    a = _part(tmp_folder, "a", "a", 2)
    b = _part(tmp_folder, "b", "b", 2)
    c = _part(tmp_folder, "c", "c", 2, crs="EPSG:3857")
    admin = "tests/data-files/admin.json"

    _merge(tmp_folder, [a, b])
    assert "Merging with DuckDB" in log()
    _merge(tmp_folder, [a, b], crs="EPSG:4326")
    assert "Merging with DuckDB" in log()
    _merge(tmp_folder, [a, admin])
    assert "Merging in memory, as DuckDB only merges local GeoParquet files" in log()
    _merge(tmp_folder, [a, c])
    assert "Merging in memory, as the datasets must be reprojected" in log()
    _merge(tmp_folder, [a, b], crs="EPSG:3857")
    assert "Merging in memory, as the datasets must be reprojected" in log()
    with pytest.raises(ValueError, match="Can't merge with DuckDB"):
        _merge(tmp_folder, [a, admin], "duckdb")


def test_merge_crs(tmp_folder, log):
    a = _part(tmp_folder, "a", "a", 2)
    c = _part(tmp_folder, "c", "c", 2, crs="EPSG:3857")
    d = _part(tmp_folder, "d", "d", 2, crs="EPSG:3857")

    def crs_of(path):
        return gpd.read_parquet(path).crs.to_epsg()

    # EPSG:4326 by default
    assert crs_of(_merge(tmp_folder, [c, d])) == 4326
    assert "Merging in memory, as the datasets must be reprojected" in log()

    # the CRS of the first dataset
    assert crs_of(_merge(tmp_folder, [c, d], crs="first")) == 3857
    assert "Merging with DuckDB" in log()
    assert crs_of(_merge(tmp_folder, [c, a], crs="first")) == 3857
    assert "Merging in memory, as the datasets must be reprojected" in log()

    # a specific CRS
    assert crs_of(_merge(tmp_folder, [a, d], crs="EPSG:3857")) == 3857
    assert "Merging in memory, as the datasets must be reprojected" in log()
    assert crs_of(_merge(tmp_folder, [c, d], crs="EPSG:3857")) == 3857
    assert "Merging with DuckDB" in log()
