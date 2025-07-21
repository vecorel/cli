from vecorel_cli.converters import Converters
from vecorel_cli.registry import Registry

Registry.ignored_datasets = []


def test_list_ids():
    c = Converters()
    result = c.list_ids()
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0] == "template"


def test_list_all():
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
        assert str(e) == "Module for converter 'non_existent' not found"
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
