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


def test_split_parts_are_numbered():
    # what make_valid() and explode() leave behind: one feature, several rows
    exploded = frame(["a", "a", "a", "b"], [box(0, 0, 1, 1)] * 4)
    converter = BaseConverter()

    numbered = converter._number_split_parts(exploded)

    assert list(numbered["id"]) == ["a", "a-2", "a-3", "b"]
    assert numbered["id"].is_unique


def test_unique_ids_are_left_alone():
    untouched = frame(["a", "b"], [box(0, 0, 1, 1), box(1, 0, 2, 1)])
    converter = BaseConverter()

    assert list(converter._number_split_parts(untouched)["id"]) == ["a", "b"]


def test_a_multipolygon_explodes_into_numbered_rows():
    parts = MultiPolygon([Polygon([(0, 0), (1, 0), (1, 1)]), Polygon([(2, 2), (3, 2), (3, 3)])])
    gdf = frame(["only"], [parts]).explode(index_parts=False)
    assert len(gdf) == 2 and not gdf["id"].is_unique

    numbered = BaseConverter()._number_split_parts(gdf)

    assert list(numbered["id"]) == ["only", "only-2"]
