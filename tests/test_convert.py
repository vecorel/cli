import json
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


CONFIG = {
    "id": "test",
    "short_name": "Test",
    "title": "Test dataset",
    "description": "Test dataset",
    "license": "CC0-1.0",
    "columns": {
        "geometry": "geometry",
        "id": "id",
        "name": "name",
    },
    "missing_schemas": {
        "properties": {
            "name": {"type": "string"},
        }
    },
}


def test_rows_are_numbered_when_no_column_is_mapped_to_id(tmp_folder):
    """A converter that maps nothing to `id` gets the row number as id, counted
    over all source files (vecorel/cli#47). A source column named `id` that is
    mapped to another target must not be overwritten by the numbering."""
    import shapely

    files = {}
    for index in range(2):
        gdf = gpd.GeoDataFrame(
            {
                "id": [f"legacy-{index}-1", f"legacy-{index}-2"],
                "name": ["a", "b"],
                "geometry": [
                    shapely.box(index * 4, 0, index * 4 + 1, 1),
                    shapely.box(index * 4 + 2, 0, index * 4 + 3, 1),
                ],
            },
            crs="EPSG:4326",
        )
        path = tmp_folder / f"src_{index}.parquet"
        gdf.to_parquet(path)
        files[str(path)] = path.name

    Converter = type(
        "IndexConverter",
        (BaseConverter,),
        {
            **CONFIG,
            "columns": {"geometry": "geometry", "name": "name", "id": "legacy"},
            "missing_schemas": {
                "properties": {"name": {"type": "string"}, "legacy": {"type": "string"}}
            },
        },
    )
    dest = tmp_folder / "converted.parquet"
    Converter().convert(dest, input_files=files)

    result = gpd.read_parquet(dest).sort_values("id")
    assert result["id"].tolist() == ["0", "1", "2", "3"]
    assert result["legacy"].tolist() == ["legacy-0-1", "legacy-0-2", "legacy-1-1", "legacy-1-2"]


def test_id_is_composed_from_id_columns(tmp_folder):
    """`id_columns` joins the named columns into `id` after the column migrations
    ran; integer-typed float columns must not render as '4.0'. It also wins over
    a mapping to `id` (often inherited), which would otherwise produce two
    columns named `id` after the rename — without overwriting a source column
    named `id` that is mapped to another target."""
    import shapely

    gdf = gpd.GeoDataFrame(
        {
            "id": ["source-1", "source-2"],
            "region": ["A", "B"],
            "block": [7.0, 40.0],  # float-typed integers, as nullable int columns often read
            "name": ["a", "b"],
            "geometry": [shapely.box(0, 0, 1, 1), shapely.box(2, 0, 3, 1)],
        },
        crs="EPSG:4326",
    )
    src = tmp_folder / "source.parquet"
    gdf.to_parquet(src)

    Converter = type(
        "ComposedConverter",
        (BaseConverter,),
        {
            **CONFIG,
            # the mapping to `id` must lose against id_columns, but `source_id`
            # must still receive the source's own `id` values
            "columns": {**CONFIG["columns"], "id": ("id", "source_id")},
            "missing_schemas": {
                "properties": {"name": {"type": "string"}, "source_id": {"type": "string"}}
            },
            "id_columns": ("campaign", "region", "block"),
            "id_separator": ":",
            "column_additions": {"campaign": 2026.0},  # must format as 2026, not 2026.0
        },
    )
    dest = tmp_folder / "converted.parquet"
    Converter().convert(dest, input_files={str(src): "source.parquet"})

    result = gpd.read_parquet(dest).sort_values("id")
    assert result["id"].tolist() == ["2026:A:7", "2026:B:40"]
    assert result["source_id"].tolist() == ["source-1", "source-2"]


def test_preserve_source_id_avoids_taken_names():
    """The name the source id moves to must be free in the frame and the mapping."""
    import shapely

    gdf = gpd.GeoDataFrame(
        {"id": ["a"], "__source_id": ["b"], "geometry": [shapely.box(0, 0, 1, 1)]},
        crs="EPSG:4326",
    )
    columns = {"id": "legacy", "__source_id": "other", "geometry": "geometry"}

    gdf, columns = BaseConverter()._preserve_source_id(gdf, columns)

    assert not gdf.columns.duplicated().any()
    assert columns["__source_id"] == "other"
    assert columns["__source_id_"] == "legacy"
    assert gdf["__source_id_"].tolist() == ["a"]
    assert gdf["__source_id"].tolist() == ["b"]


def test_suffix_duplicate_ids_avoids_existing_ids_and_compares_as_strings():
    """A numbered id must not collide with an id the source already carries
    (x, x, x~1), and repeats hidden by mixed types (1 vs "1") must be caught:
    the writer merges both into the string "1"."""
    import shapely

    from vecorel_cli.vecorel.util import suffix_duplicate_ids

    box = shapely.box(0, 0, 1, 1)
    gdf = gpd.GeoDataFrame({"id": ["x", "x", "x~1"], "geometry": [box] * 3}, crs="EPSG:4326")
    gdf, count = suffix_duplicate_ids(gdf)
    assert count == 2
    assert gdf["id"].is_unique, gdf["id"].tolist()

    gdf = gpd.GeoDataFrame({"id": [1, "1"], "geometry": [box] * 2}, crs="EPSG:4326")
    gdf, count = suffix_duplicate_ids(gdf)
    assert count == 2
    assert sorted(gdf["id"]) == ["1~1", "1~2"]


def test_features_keep_their_row_when_repaired(tmp_folder):
    """Multi-part geometries are not split into one row per polygon: features keep
    the geometry modeling of the source, so their ids and attributes stay 1:1 with
    it. A repaired invalid polygon stays one feature as a MultiPolygon, and rows
    without a polygonal geometry are dropped."""
    import shapely

    gdf = gpd.GeoDataFrame(
        {
            "id": ["square", "multi", "bowtie", "point", "collection", "debris", "overlap", "nested"],
            "name": ["a", "b", "c", "d", "e", "f", "g", "h"],
            "geometry": [
                shapely.Polygon([(0, 0), (0, 1), (1, 1), (1, 0)]),
                shapely.MultiPolygon(
                    [
                        shapely.Polygon([(2, 0), (2, 1), (3, 1), (3, 0)]),
                        shapely.Polygon([(4, 0), (4, 1), (5, 1), (5, 0)]),
                    ]
                ),
                shapely.Polygon([(6, 0), (7, 1), (7, 0), (6, 1)]),
                shapely.Point(10, 0),
                # what make_valid() can emit: the polygonal part must survive alone
                shapely.GeometryCollection(
                    [
                        shapely.Polygon([(8, 0), (8, 1), (9, 1), (9, 0)]),
                        shapely.LineString([(8, 2), (9, 2)]),
                    ]
                ),
                shapely.GeometryCollection([shapely.LineString([(10, 2), (11, 2)])]),
                # members of a collection may overlap; the row must survive as a
                # valid geometry instead of becoming an invalid MultiPolygon
                shapely.GeometryCollection([shapely.box(12, 0, 14, 2), shapely.box(13, 1, 15, 3)]),
                shapely.GeometryCollection(
                    [
                        shapely.GeometryCollection([shapely.box(16, 0, 17, 1)]),
                        shapely.LineString([(16, 2), (17, 2)]),
                    ]
                ),
            ],
        },
        crs="EPSG:4326",
    )
    src = tmp_folder / "source.parquet"
    gdf.to_parquet(src)

    Converter = type("KeepConverter", (BaseConverter,), dict(CONFIG))
    dest = tmp_folder / "converted.parquet"
    Converter().convert(dest, input_files={str(src): "source.parquet"})

    result = gpd.read_parquet(dest)
    types = dict(zip(result["id"], result.geometry.geom_type))
    assert sorted(types) == ["bowtie", "collection", "multi", "nested", "overlap", "square"]
    assert types["square"] == "Polygon"
    assert types["multi"] == "MultiPolygon"
    assert types["bowtie"] == "MultiPolygon"
    assert types["collection"] == "MultiPolygon"
    assert types["nested"] == "MultiPolygon"
    assert result.geometry.is_valid.all()


def test_duplicate_ids_get_numbered(tmp_folder):
    """id must be unique within a file; when the source repeats ids (here across
    two input files), the repeats get a ~<n> suffix (vecorel/cli#47)."""
    import shapely

    files = {}
    for index in range(2):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["same", f"other-{index}"],
                "name": ["a", "b"],
                "geometry": [
                    shapely.box(index * 4, 0, index * 4 + 1, 1),
                    shapely.box(index * 4 + 2, 0, index * 4 + 3, 1),
                ],
            },
            crs="EPSG:4326",
        )
        path = tmp_folder / f"dup_src_{index}.parquet"
        gdf.to_parquet(path)
        files[str(path)] = path.name

    Converter = type("DupConverter", (BaseConverter,), dict(CONFIG))
    dest = tmp_folder / "converted.parquet"
    Converter().convert(dest, input_files=files)

    assert sorted(gpd.read_parquet(dest)["id"]) == ["other-0", "other-1", "same~1", "same~2"]


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


@pytest.mark.parametrize("bom", [False, True], ids=["without-bom", "with-bom"])
def test_read_geojson_decodes_utf8(tmp_folder, cp1252_locale, bom):
    file_path = tmp_folder / "umlaut.json"
    feature = {
        "type": "Feature",
        "id": "1",
        "properties": {"name": "Grünland"},
        "geometry": {"type": "Point", "coordinates": [0, 0]},
    }
    file_path.write_text(
        # ensure_ascii=False so the file really holds multi-byte UTF-8, not an escape sequence
        json.dumps({"type": "FeatureCollection", "features": [feature]}, ensure_ascii=False),
        encoding="utf-8-sig" if bom else "utf-8",
    )

    gdf = BaseConverter().read_geojson(str(file_path))

    assert gdf["name"].iloc[0] == "Grünland"


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


@pytest.mark.parametrize("choice", ["example"])
def test_converter_can_keep_the_constants_in_columns(tmp_folder, monkeypatch, choice):
    """A conversion that writes one part of a dataset cannot let constants move
    into the collection metadata: constant is then judged over the part."""
    import pyarrow.parquet as pq

    from tests.datasets.example import Converter

    dest = tmp_folder / "hydrated.parquet"
    monkeypatch.setattr(Converter, "dehydrate", False)
    ConvertData(choice).convert(dest, cache=(test_path / choice))

    schema = pq.ParquetFile(dest).schema_arrow
    collection = json.loads(schema.metadata[b"collection"])
    for key in ("admin:country_code", "admin:subdivision_code", "determination_datetime"):
        assert key in schema.names, f"{key} should have stayed a column"
        assert key not in collection, f"{key} should not be in the collection metadata"


def test_default_variant_is_chosen_before_get_urls():
    """A converter that overrides get_urls() must see the default variant, so the
    default lives in convert() and not in the base get_urls() it replaces."""

    class Converter(BaseConverter):
        id = "variants"
        # oldest first: the latest year is still the default
        variants = {
            "2024": "https://example.com/2024.gpkg",
            "2025": "https://example.com/2025.gpkg",
        }

        def get_urls(self):
            # like the converters that look their files up by year
            return {f"https://example.com/{self.variant}/": f"{self.variant}.gpkg"}

    converter = Converter()
    converter.select_variant(None)
    assert converter.variant == "2025"
    assert converter.get_urls() == {"https://example.com/2025/": "2025.gpkg"}

    converter.select_variant("2024")
    assert converter.variant == "2024"
    assert converter.get_urls() == {"https://example.com/2024/": "2024.gpkg"}


def test_default_variant_is_the_first_declared_unless_the_variants_are_years():
    class Converter(BaseConverter):
        id = "variants"
        variants = {"full": "https://example.com/full.gpkg", "2025": "https://example.com/2025"}

    converter = Converter()
    converter.select_variant(None)
    assert converter.variant == "full"


def test_get_urls_rejects_an_unknown_variant():
    class Converter(BaseConverter):
        id = "variants"
        variants = {"2025": "https://example.com/2025.gpkg"}

    converter = Converter()
    converter.select_variant("2025")
    assert converter.get_urls() == "https://example.com/2025.gpkg"

    converter.select_variant("1999")
    with pytest.raises(ValueError, match="Unknown variant '1999'"):
        converter.get_urls()
