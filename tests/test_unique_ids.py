"""The two ways a file was written with ids that repeat."""

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon, box

from vecorel_cli.conversion.base import BaseConverter


def frame(ids, geometries):
    return gpd.GeoDataFrame({"id": ids}, geometry=geometries, crs="EPSG:4326")


def test_id_from_index_numbers_the_whole_frame():
    # read_data() concatenates the source files and pandas keeps each file's index
    one = frame([None, None], [box(0, 0, 1, 1), box(1, 0, 2, 1)])
    two = frame([None, None], [box(2, 0, 3, 1), box(3, 0, 4, 1)])
    concatenated = pd.concat([one, two])
    assert not concatenated.index.is_unique, "the fixture must reproduce the repeated index"

    numbered = BaseConverter._id_from_index(concatenated)

    assert numbered["id"].is_unique
    assert list(numbered["id"]) == [0, 1, 2, 3]


def test_duplicates_keep_the_source_id_and_gain_a_suffix():
    # what make_valid() and explode() leave behind: one feature, several rows
    exploded = frame(["a", "a", "a", "b"], [box(0, 0, 1, 1)] * 4)

    suffixed = BaseConverter()._suffix_duplicate_ids(exploded)

    assert list(suffixed["id"]) == ["a", "a_1", "a_2", "b"]
    assert suffixed["id"].is_unique


def test_a_suffix_the_source_already_uses_is_skipped():
    clashing = frame(["1", "1", "1_1"], [box(0, 0, 1, 1)] * 3)

    suffixed = BaseConverter()._suffix_duplicate_ids(clashing)

    assert list(suffixed["id"]) == ["1", "1_2", "1_1"]
    assert suffixed["id"].is_unique


def test_unique_ids_are_left_alone():
    untouched = frame(["a", "b"], [box(0, 0, 1, 1), box(1, 0, 2, 1)])

    assert list(BaseConverter()._suffix_duplicate_ids(untouched)["id"]) == ["a", "b"]


def test_a_multipolygon_explodes_into_suffixed_rows():
    parts = MultiPolygon([Polygon([(0, 0), (1, 0), (1, 1)]), Polygon([(2, 2), (3, 2), (3, 3)])])
    gdf = frame(["only"], [parts]).explode(index_parts=False)
    assert len(gdf) == 2 and not gdf["id"].is_unique

    suffixed = BaseConverter()._suffix_duplicate_ids(gdf)

    assert list(suffixed["id"]) == ["only", "only_1"]
