import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.types as pat

from vecorel_cli.encoding.geoparquet import GeoParquet
from vecorel_cli.vecorel.collection import Collection


def test_init_paths(tmp_folder):
    fpath = str(tmp_folder / "test.parquet")
    ppath = Path(fpath)

    assert GeoParquet(fpath).uri == ppath
    assert GeoParquet(ppath).uri == ppath


def test_get_format():
    assert (
        GeoParquet("tests/data-files/inspire.parquet").get_format() == "GeoParquet, version 1.1.0"
    )


def test_get_collection_exists():
    geojson = GeoParquet("tests/data-files/inspire.parquet")

    collection = geojson.get_collection()

    assert isinstance(collection, dict)
    fields = list(collection.keys())
    fields.sort()
    assert fields == ["collection", "determination_datetime", "schemas", "schemas:custom"]
    assert "inspire" in collection["schemas"]


def test_get_collection_does_not_exist():
    collection = GeoParquet("invalid.parquet").get_collection()
    assert isinstance(collection, Collection)
    assert collection.is_empty()


def test_get_collection_returns_existing(tmp_folder):
    file_path = tmp_folder / "test.parquet"
    test_collection = Collection({"test": "data"})

    geojson = GeoParquet(file_path)
    geojson.collection = test_collection

    result = geojson.get_collection()
    assert isinstance(result, Collection)
    assert result == test_collection


def test_postprocess(tmp_parquet_file):
    # Degrade a compliant file to what external tools such as DuckDB or GDAL may produce:
    # large_string/large_binary columns, a naive microsecond timestamp, nullable columns,
    # no bbox column, GeoParquet 1.0.0
    src = pq.read_table("tests/data-files/inspire.parquet")
    fields = []
    arrays = []
    for i, field in enumerate(src.schema):
        if field.name == "bbox":
            continue
        if pat.is_string(field.type):
            dtype = pa.large_string()
        elif pat.is_binary(field.type):
            dtype = pa.large_binary()
        else:
            dtype = field.type
        fields.append(pa.field(field.name, dtype, nullable=True))
        arrays.append(src.column(i).cast(dtype))
    fields.append(pa.field("determination_datetime", pa.timestamp("us")))
    arrays.append(pa.array([1672531200000000] * len(src), type=pa.timestamp("us")))

    metadata = dict(src.schema.metadata)
    geo = json.loads(metadata[b"geo"])
    geo["version"] = "1.0.0"
    geo["columns"]["geometry"].pop("covering", None)
    metadata[b"geo"] = json.dumps(geo).encode("utf-8")
    degraded = pa.table(arrays, schema=pa.schema(fields, metadata=metadata))
    pq.write_table(degraded, tmp_parquet_file, store_schema=True)

    gp = GeoParquet(tmp_parquet_file)
    assert gp.postprocess(geoparquet_version="1.1.0", compression="zstd") is True
    # a second run detects the compliant file and doesn't rewrite it
    assert gp.postprocess(geoparquet_version="1.1.0", compression="zstd") is False
    # unless a different compression is requested
    assert gp.postprocess(geoparquet_version="1.1.0", compression="brotli") is True

    with pq.ParquetFile(tmp_parquet_file) as result:
        schema = result.schema_arrow
        metadata = result.metadata.metadata

    field = schema.field("geometry")
    assert field.type == pa.binary()
    assert not field.nullable
    field = schema.field("id")
    assert field.type == pa.string()
    assert not field.nullable
    assert schema.field("inspire:id").type == pa.string()
    assert schema.field("determination_datetime").type == pa.timestamp("ms", tz="UTC")

    bbox = schema.field("bbox")
    assert pat.is_struct(bbox.type)
    assert bbox.type.field("xmin").type == pa.float64()

    geo = json.loads(metadata[b"geo"])
    assert geo["version"] == "1.1.0"
    assert geo["columns"]["geometry"]["covering"]["bbox"]["xmin"] == ["bbox", "xmin"]
    assert b"collection" in metadata

    # data is intact
    data = pq.read_table(tmp_parquet_file)
    assert data.num_rows == src.num_rows
    assert data["id"].to_pylist() == src["id"].to_pylist()
    assert data["geometry"].to_pylist() == src["geometry"].to_pylist()

    # a downgrade removes the covering metadata, which only exists since GeoParquet 1.1
    assert gp.postprocess(geoparquet_version="1.0.0", compression="brotli") is True
    with pq.ParquetFile(tmp_parquet_file) as pf:
        geo = json.loads(pf.metadata.metadata[b"geo"])
    assert geo["version"] == "1.0.0"
    assert "covering" not in geo["columns"]["geometry"]


def test_read_keeps_integers_that_have_a_null(tmp_parquet_file):
    # pandas turns an integer column with a missing value into float64, after which
    # every value in it reads as a float and validation rejects the column
    src = pq.read_table("tests/data-files/inspire.parquet")
    counts = pa.array([7] * (len(src) - 1) + [None], pa.uint32())
    table = src.append_column(pa.field("count", pa.uint32(), nullable=True), counts)

    metadata = dict(src.schema.metadata)
    collection = json.loads(metadata[b"collection"])
    collection["schemas:custom"]["properties"]["count"] = {"type": "uint32"}
    metadata[b"collection"] = json.dumps(collection).encode("utf-8")
    pq.write_table(table.replace_schema_metadata(metadata), tmp_parquet_file, store_schema=True)

    data = GeoParquet(tmp_parquet_file).read()
    assert str(data["count"].dtype) == "UInt32"
    assert isinstance(data["count"].iloc[0], np.uint32)
    assert pd.isna(data["count"].iloc[-1])

    from vecorel_cli.validate import ValidateData

    assert ValidateData().validate(tmp_parquet_file).errors == []
