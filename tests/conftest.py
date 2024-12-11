import tempfile
from pytest import fixture

from fiboa_cli import convert_utils


@fixture
def tmp_file():
    with tempfile.NamedTemporaryFile() as out:
        yield out


def raiser(message):
    def _method(*args, **kwargs):
        raise Exception(message)
    return _method


@fixture
def block_stream_file():
    # disable stream_file so we don't accidentally download files during test

    original = convert_utils.stream_file
    convert_utils.stream_file = raiser("convert_utils.stream_file() should not be called during test")
    yield
    convert_utils.stream_file = original

