import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from loguru import logger

from vecorel_cli.conversion.base import BaseConverter
from vecorel_cli.convert import ConvertData
from vecorel_cli.registry import Registry
from vecorel_cli.validate import ValidateData
from vecorel_cli.vecorel.hilbert import crs_total_bounds, hilbert_distances_from_bounds


@pytest.fixture(autouse=True)
def registry_reset():
    ignored = Registry.ignored_datasets
    src_package = Registry.src_package
    Registry.src_package = "tests"
    yield
    Registry.ignore_datasets = ignored
    Registry.src_package = src_package


test_path = Path("tests/data-files/convert")


@pytest.mark.parametrize("choice", ["example"])
def test_converter(tmp_folder, choice):
    dest = tmp_folder / "converted.parquet"
    converter = ConvertData(choice)
    converter.convert(dest, cache=(test_path / choice))

    assert dest.exists(), f"Expected file {dest} to be created."

    # todo: Validation works, but fails for the created file
    validator = ValidateData()
    validation_result = validator.validate(
        dest,
        num=100,
        schema_map={},
    )
    assert validation_result.errors == []


@pytest.mark.parametrize("choice", ["example"])
def test_converter_hilbert_curve_order(tmp_folder, choice):
    """The converter must emit rows in Hilbert-curve order against the CRS's
    total bounds. This is what makes per-partition outputs of the same dataset
    mergeable without re-sorting: they all share a CRS-derived Hilbert grid."""
    dest = tmp_folder / "converted.parquet"
    ConvertData(choice).convert(dest, cache=(test_path / choice))

    gdf = gpd.read_parquet(dest)
    assert len(gdf) > 1, "Need at least 2 rows to verify ordering."

    total_bounds = crs_total_bounds(gdf.crs)
    bounds = gdf.geometry.bounds.to_numpy(dtype=np.float64, copy=False)
    keys = hilbert_distances_from_bounds(bounds, total_bounds)

    # NB: keys are uint64 — np.diff would wrap descents into huge positives
    # and never flag them; compare adjacent keys directly instead.
    descents = keys[1:] < keys[:-1]
    if np.any(descents):
        bad = int(np.argmax(descents))
        raise AssertionError(
            "Output rows are not in non-decreasing Hilbert order against the "
            f"CRS total bounds ({total_bounds}).\n"
            f"  First out-of-order pair at index {bad}->{bad + 1}: "
            f"key {int(keys[bad])} > {int(keys[bad + 1])}."
        )


def test_crs_total_bounds_geographic():
    # Geographic CRS without a more restrictive area_of_use falls back to world.
    assert crs_total_bounds("EPSG:4326") == (-180.0, -90.0, 180.0, 90.0)


def test_crs_total_bounds_etrs89():
    # EPSG:4258 is geographic with a European area_of_use; the returned bounds
    # must reflect that AoU rather than world bounds (otherwise Hilbert keys
    # for European data would all be quantised into one tiny cell).
    bounds = crs_total_bounds("EPSG:4258")
    assert bounds[0] > -180.0 and bounds[2] < 180.0, bounds
    assert bounds[1] > -90.0 and bounds[3] < 90.0, bounds


def test_hilbert_distances_match_public_geopandas_api():
    # hilbert_distances_from_bounds exists for callers that hold bbox columns
    # without decoded geometry; it must stay identical to the public
    # GeoSeries.hilbert_distance, which guards its private-API internals.
    from shapely.geometry import box

    rng = np.random.default_rng(42)
    xs = rng.uniform(4.0, 6.0, 50)
    ys = rng.uniform(51.0, 53.0, 50)
    geoms = [box(x, y, x + 0.01, y + 0.01) for x, y in zip(xs, ys)]
    gdf = gpd.GeoDataFrame(geometry=geoms, crs="EPSG:4326")
    total = crs_total_bounds(gdf.crs)
    public = gdf.geometry.hilbert_distance(total_bounds=list(total), level=16).to_numpy()
    ours = hilbert_distances_from_bounds(
        gdf.geometry.bounds.to_numpy(dtype=np.float64), total, level=16
    )
    assert np.array_equal(public.astype(np.uint64), ours)


def test_crs_total_bounds_antimeridian():
    # NZGD2000 / NZTM: the area of use spans the antimeridian (west > east);
    # the projected bounds must still be finite and non-degenerate.
    xmin, ymin, xmax, ymax = crs_total_bounds("EPSG:2193")
    assert xmax > xmin and ymax > ymin
    assert all(np.isfinite(v) for v in (xmin, ymin, xmax, ymax))


def test_hilbert_sort_falls_back_without_area_of_use():
    # A custom projected CRS without area_of_use must not fail the conversion;
    # the sorter falls back to the dataset's own bounds.
    from shapely.geometry import Point

    from vecorel_cli.vecorel.hilbert import hilbert_sort_geodataframe

    crs = "+proj=tmerc +lat_0=0 +lon_0=9 +k=1 +x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs"
    gdf = gpd.GeoDataFrame(geometry=[Point(0, 0), Point(1000, 1000), Point(10, 10)], crs=crs)
    out = hilbert_sort_geodataframe(gdf)
    assert len(out) == 3


def test_not_existing_converter(tmp_folder):
    with pytest.raises(Exception, match="Converter 'not_existing' not found"):
        converter = ConvertData("not_existing")
        converter.convert(tmp_folder / "converted.parquet")


@pytest.mark.parametrize("choice", ["invalid_syntax", "invalid_name"])
def test_invalid_converter(tmp_folder, choice):
    with pytest.raises(Exception, match=f"Converter for '{choice}' not available or faulty:"):
        converter = ConvertData(choice)
        converter.convert(tmp_folder / "converted.parquet")


def test_template_from_package_folder():
    Registry.src_package = "vecorel_cli"
    Registry.ignored_datasets = []
    converter = ConvertData("template")
    assert isinstance(converter, ConvertData), "Should succeed and not throw an exception"


def test_data_access_exception(capsys, tmp_folder):
    # todo: use fixture
    logger.remove()
    logger.add(sys.stdout, format="{message}", level="DEBUG", colorize=False)

    with pytest.raises(Exception, match="Please provide the input data."):
        converter = ConvertData("data_access")
        converter.convert(tmp_folder / "converted.parquet")

    out, err = capsys.readouterr()

    assert isinstance(converter.converter, BaseConverter)
    assert converter.converter.data_access in out
