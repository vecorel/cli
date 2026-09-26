import re

import pytest
from jsonschema.exceptions import ValidationError

from vecorel_cli.registry import Registry
from vecorel_cli.validate import ValidateData

inspire_str = "https://fiboa.github.io/inspire-extension/v0.3.0/schema.yaml"
inspire_re = re.compile(r"https://fiboa.github.io/inspire-extension/v0.3.\d+/schema.yaml")

tests = [
    # non-existing files
    ("invalid.json", [FileNotFoundError()], []),
    ("invalid.parquet", [FileNotFoundError()], []),
    # valid files
    ("tests/data-files/admin.json", True, []),
    ("tests/data-files/inspire.json", True, []),
    ("tests/data-files/inspire.parquet", True, []),
    # invalid files
    (
        "tests/data-files/inspire-invalid.json",
        [ValidationError("6467975 is not of type 'string'")],
        [],
    ),
    # multiple collections, valid files
    ("tests/data-files/mixed.json", True, []),
    ("tests/data-files/mixed.parquet", True, []),
    # multiple collections, invalid files
    (
        "tests/data-files/mixed-invalid.json",
        [
            Exception("'DEE' is too long"),
            Exception("'DEE' does not match '^[A-Z]{2}$'"),
        ],
        [],
    ),
    (
        "tests/data-files/mixed-invalid.parquet",
        [
            Exception("admin:country_code: String 'DEE' is longer than the maximum length of 2."),
            Exception(
                "admin:country_code: String 'DEE' does not match the required pattern: ^[A-Z]{2}$."
            ),
        ],
        [],
    ),
    # Test required_extensions
    (
        "tests/data-files/inspire.json",
        True,
        [inspire_str],
    ),
    (
        "tests/data-files/inspire.json",
        True,
        [inspire_re],
    ),
    (
        "tests/data-files/mixed.json",
        [
            Exception(
                "Collection 'de': Required schema https://fiboa.github.io/inspire-extension/v0.3.0/schema.yaml not found"
            )
        ],
        [inspire_str],
    ),
    (
        "tests/data-files/mixed.json",
        [
            Exception(
                r"Collection 'de': Required schema https://fiboa.github.io/inspire-extension/v0.3.\d+/schema.yaml not found"
            )
        ],
        [inspire_re],
    ),
]


@pytest.mark.parametrize("test", tests)
def test_validate(test):
    filepath, expected, req_schemas = test

    Registry.required_extensions = req_schemas
    result = ValidateData().validate(filepath)
    Registry.required_extensions = []

    if expected is True:
        assert result.errors == []
        assert result.is_valid()
    else:
        assert isinstance(result.errors, list)
        assert len(result.errors) == len(expected), "More or less errors than expected"
        for idx, error in enumerate(result.errors):
            expect = expected[idx]
            if isinstance(expect, Exception):
                assert isinstance(error, type(expect)), (
                    f"Expected {type(expect)} but got {type(error)}"
                )
                message = error.message if isinstance(error, ValidationError) else str(error)
                if isinstance(expect, ValidationError):
                    assert message == expect.message
                elif isinstance(expect, FileNotFoundError):
                    pass  # ignore exact message for FileNotFoundError
                elif isinstance(expect, Exception):
                    assert message == str(expect)
            else:
                assert error == expect

        assert not result.is_valid()


def _write_collections(path, collections, columns, schemas):
    import geopandas as gpd
    import shapely

    from vecorel_cli.encoding.geoparquet import GeoParquet

    n = len(collections)
    gdf = gpd.GeoDataFrame(
        {
            "id": [str(i) for i in range(n)],
            "collection": collections,
            **columns,
            "geometry": [shapely.box(i, 0, i + 1, 1) for i in range(n)],
        },
        crs="EPSG:4326",
    )
    gp = GeoParquet(path)
    gp.set_collection({"schemas": schemas})
    gp.write(gdf, dehydrate=False)


def test_validate_rejects_features_without_a_known_collection(tmp_parquet_file):
    core = "https://vecorel.org/specification/v0.1.0/schema.yaml"
    _write_collections(tmp_parquet_file, ["a", None, "x"], {}, {"a": [core], "b": [core]})

    errors = [str(e) for e in ValidateData().validate(tmp_parquet_file).errors]
    assert errors == [
        "collection: 1 rows have no collection",
        "collection: Not found in schemas: x",
    ]


def test_validate_reports_a_missing_collection_column(tmp_parquet_file):
    import geopandas as gpd
    import shapely

    from vecorel_cli.encoding.geoparquet import GeoParquet

    core = "https://vecorel.org/specification/v0.1.0/schema.yaml"
    gdf = gpd.GeoDataFrame(
        {"id": ["1", "2"], "geometry": [shapely.box(0, 0, 1, 1)] * 2}, crs="EPSG:4326"
    )
    gp = GeoParquet(tmp_parquet_file)
    gp.set_collection({"schemas": {"a": [core], "b": [core]}})
    gp.write(gdf, dehydrate=False)

    errors = [str(e) for e in ValidateData().validate(tmp_parquet_file).errors]
    assert errors == ["collection: Required field is missing"]


def test_validate_checks_required_properties_per_collection(tmp_parquet_file):
    core = "https://vecorel.org/specification/v0.1.0/schema.yaml"
    admin = "https://vecorel.org/administrative-division-extension/v0.1.0/schema.yaml"
    schemas = {"a": [core, admin], "b": [core]}
    columns = {"admin:country_code": ["DE", None, None]}
    _write_collections(tmp_parquet_file, ["a", "a", "b"], columns, schemas)

    errors = [str(e) for e in ValidateData().validate(tmp_parquet_file).errors]
    assert errors == ["admin:country_code: Required field has no value for collection 'a'"]

    columns = {"admin:country_code": ["DE", "DE", None]}
    _write_collections(tmp_parquet_file, ["a", "a", "b"], columns, schemas)
    assert ValidateData().validate(tmp_parquet_file).errors == []
