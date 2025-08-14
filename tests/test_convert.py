import sys
from pathlib import Path

import pytest
from loguru import logger

from vecorel_cli.conversion.base import BaseConverter
from vecorel_cli.convert import ConvertData
from vecorel_cli.registry import Registry
from vecorel_cli.validate import ValidateData


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
