import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import shapely

from vecorel_cli.vecorel.hilbert import (
    bounds_array_for_table,
    crs_total_bounds,
    ensure_hilbert_sorted,
    hilbert_keys_for_table,
    hilbert_reference_bounds,
)

# A bare projection definition without an area of use,
# like the unnamed "MGI / Austria Lambert" in Austria's 2018 edition
CUSTOM_CRS = "+proj=laea +lat_0=52 +lon_0=10 +x_0=4321000 +y_0=3210000 +units=m"


def test_hilbert_reference_bounds_from_crs():
    assert hilbert_reference_bounds("EPSG:4326") == (-180.0, -90.0, 180.0, 90.0)


def test_hilbert_reference_bounds_fallback():
    fallback = [1.0, 2.0, 3.0, 4.0]
    assert hilbert_reference_bounds(CUSTOM_CRS, fallback) == (1.0, 2.0, 3.0, 4.0)
    assert hilbert_reference_bounds(CUSTOM_CRS) is None


def _make_table(points, with_bbox=True, metadata=None):
    geometries = [shapely.Point(x, y).buffer(0.1) for x, y in points]
    wkb = [shapely.to_wkb(g) for g in geometries]
    bounds = shapely.bounds(np.array(geometries, dtype=object))
    arrays = {
        "id": pa.array([str(i) for i in range(len(points))], type=pa.string()),
        "geometry": pa.array(wkb, type=pa.binary()),
    }
    if with_bbox:
        arrays["bbox"] = pa.StructArray.from_arrays(
            [bounds[:, 0], bounds[:, 1], bounds[:, 2], bounds[:, 3]],
            names=["xmin", "ymin", "xmax", "ymax"],
        )
    table = pa.table(arrays)
    if metadata:
        table = table.replace_schema_metadata(metadata)
    return table


def test_bounds_array_bbox_and_wkb_paths_agree():
    points = [(0, 0), (10, 10), (5, 5)]
    with_bbox = _make_table(points, with_bbox=True)
    without_bbox = _make_table(points, with_bbox=False)

    np.testing.assert_allclose(
        bounds_array_for_table(with_bbox, "geometry"),
        bounds_array_for_table(without_bbox, "geometry"),
    )


def test_ensure_hilbert_sorted(tmp_folder):
    path = str(tmp_folder / "unsorted.parquet")
    # scattered, deliberately not in Hilbert order
    points = [(30, 40), (-120, -30), (5, 5), (100, 60), (-60, 10)]
    metadata = {
        b"geo": json.dumps({"primary_column": "geometry", "columns": {"geometry": {}}}).encode(),
        b"collection": b'{"schemas": {}}',
    }
    table = _make_table(points, metadata=metadata)
    pq.write_table(table, path)

    total_bounds = crs_total_bounds("EPSG:4326")
    keys = hilbert_keys_for_table(table, "geometry", total_bounds)
    assert not bool(np.all(keys[1:] >= keys[:-1])), "Test data must start unsorted"

    assert ensure_hilbert_sorted(path, "geometry", total_bounds, "zstd") is True

    result = pq.read_table(path)
    sorted_keys = hilbert_keys_for_table(result, "geometry", total_bounds)
    assert bool(np.all(sorted_keys[1:] >= sorted_keys[:-1]))
    # data is intact, schema stays narrow, metadata is preserved
    assert sorted(result["id"].to_pylist()) == sorted(table["id"].to_pylist())
    assert result.schema.field("geometry").type == pa.binary()
    assert result.schema.field("id").type == pa.string()
    assert result.schema.metadata[b"geo"] == metadata[b"geo"]
    assert result.schema.metadata[b"collection"] == metadata[b"collection"]

    # a second run is a no-op
    assert ensure_hilbert_sorted(path, "geometry", total_bounds, "zstd") is False
