import pytest

from vecorel_cli.converters import Converters
from vecorel_cli.registry import Registry


@pytest.fixture(autouse=True)
def registry_reset():
    ignored = Registry.ignored_datasets
    src_package = Registry.src_package
    yield
    Registry.ignore_datasets = ignored
    Registry.src_package = src_package


def test_list_ids():
    Registry.ignored_datasets = []
    c = Converters()
    result = c.list_ids()
    assert isinstance(result, list)
    assert len(result) == 1
    assert "template" in result


def test_list_ids_other_module():
    Registry.src_package = "tests"
    c = Converters()
    result = c.list_ids()
    assert isinstance(result, list)
    assert len(result) >= 2
    assert "data_access" in result
    assert "example" in result


def test_list_all():
    Registry.ignored_datasets = []
    c = Converters()
    result = c.list_all()
    assert isinstance(result, dict)
    assert len(result.keys()) == 1
    assert "template" in result
    assert isinstance(result["template"], dict)
    assert "short_name" in result["template"]
    assert result["template"]["short_name"] == "Country, Region, etc."
    assert "license" in result["template"]
    assert result["template"]["license"] == "CC-BY-4.0"


def test_load():
    Registry.ignored_datasets = []
    c = Converters()
    converter = c.load("template")
    assert converter is not None
    assert hasattr(converter, "convert")
    assert callable(converter.convert)


def test_load_invalid():
    c = Converters()
    try:
        c.load("non_existent")
    except ValueError as e:
        assert str(e) == "Converter 'non_existent' not found"
    else:
        assert False, "Expected ValueError was not raised"


def test_load_ignored():
    c = Converters()
    try:
        c.load("__init__")
    except ValueError as e:
        assert str(e) == "Converter with id '__init__' is not an allowed converter filename."
    else:
        assert False, "Expected ValueError was not raised"
