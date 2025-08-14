import pytest

from vecorel_cli.encoding.auto import create_encoding
from vecorel_cli.encoding.geojson import GeoJSON
from vecorel_cli.encoding.geoparquet import GeoParquet

tests = [
    # existing files
    ("tests/data-files/inspire.json", GeoJSON),
    ("tests/data-files/inspire.parquet", GeoParquet),
    # non-existing files
    ("invalid.json", GeoJSON),
    ("invalid.parquet", GeoParquet),
    ("invalid.geojson", GeoJSON),
    ("invalid.geoparquet", GeoParquet),
    # non-existing encoding
    ("invalid.txt", None),
    ("invalid", None),
]


@pytest.mark.parametrize("test", tests)
def test_create_encoding(test):
    filepath, obj_type = test

    if filepath is None:
        with pytest.raises(TypeError):
            create_encoding(filepath)
    elif obj_type is None:
        with pytest.raises(ValueError):
            create_encoding(filepath)
    else:
        encoding = create_encoding(filepath)
        assert isinstance(encoding, obj_type)
