import pytest
from jsonschema.exceptions import ValidationError

from vecorel_cli.validate import ValidateData

tests = [
    # non-existing files
    ("invalid.json", [FileNotFoundError()]),
    ("invalid.parquet", [FileNotFoundError()]),
    # valid files
    ("tests/data-files/admin.json", True),
    ("tests/data-files/inspire.json", True),
    ("tests/data-files/inspire.parquet", True),
    # invalid files
    ("tests/data-files/inspire-invalid.json", [ValidationError("6467975 is not of type 'string'")]),
    # multiple collections, valid files
    ("tests/data-files/mixed.json", True),
    ("tests/data-files/mixed.parquet", True),
    # multiple collections, invalid files
    (
        "tests/data-files/mixed-invalid.json",
        [
            Exception("'DEE' is too long"),
            Exception("'DEE' does not match '^[A-Z]{2}$'"),
        ],
    ),
    (
        "tests/data-files/mixed-invalid.parquet",
        [
            Exception("admin:country_code: String 'DEE' is longer than the maximum length of 2."),
            Exception(
                "admin:country_code: String 'DEE' does not match the required pattern: ^[A-Z]{2}$."
            ),
        ],
    ),
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
