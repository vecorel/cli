import pytest

from vecorel_cli.validate import ValidateData

tests = [
    # valid files
    ("tests/data-files/admin.json", True),
    ("tests/data-files/inspire.json", True),
    ("tests/data-files/inspire.parquet", True),
    # invalid files
    # todo
]


@pytest.mark.parametrize("test", tests)
def test_validate(test):
    filepath, expected = test

    result = ValidateData().validate(filepath)
    assert result == expected
