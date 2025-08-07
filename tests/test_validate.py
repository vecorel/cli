import pytest
from jsonschema.exceptions import ValidationError

from vecorel_cli.validate import ValidateData

tests = [
    # valid files
    ("tests/data-files/admin.json", True),
    ("tests/data-files/inspire.json", True),
    ("tests/data-files/inspire.parquet", True),
    # non-existing files
    ("invalid.json", [FileNotFoundError()]),
    ("invalid.parquet", [FileNotFoundError()]),
    # invalid files
    ("tests/data-files/inspire-invalid.json", [ValidationError("6467975 is not of type 'string'")]),
    # todo
]


@pytest.mark.parametrize("test", tests)
def test_validate(test):
    filepath, expected = test

    result = ValidateData().validate(filepath)
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
                if isinstance(error, ValidationError):
                    assert error.message == expect.message
            else:
                assert error == expect

        assert not result.is_valid()
