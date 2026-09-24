import threading
import zipfile
from contextlib import contextmanager

import inflate64

# Deflate64 ("enhanced deflate", ZIP method 9) is what Windows writes for large archives,
# and python's zipfile cannot read it. inflate64, a dependency of py7zr, decodes it.
ZIP_DEFLATED64 = 9

_lock = threading.Lock()
_users = 0
_original_get_decompressor = zipfile._get_decompressor


class _Deflate64Decompressor:
    """The interface zipfile.ZipExtFile expects of a decompressor other than zlib's
    (Python 3.11 to 3.14): decompress(data) and eof."""

    def __init__(self):
        self._inflater = inflate64.Inflater()

    @property
    def eof(self):
        return self._inflater.eof

    def decompress(self, data):
        return self._inflater.inflate(data)


def _get_decompressor(compress_type):
    if compress_type == ZIP_DEFLATED64:
        return _Deflate64Decompressor()
    return _original_get_decompressor(compress_type)


@contextmanager
def deflate64_zip():
    """Let zipfile read Deflate64 members for the duration of the block.

    The hook is process-global, so it is counted: installed by the first block to enter
    and restored by the last to exit, whatever order overlapping blocks exit in."""
    global _users
    with _lock:
        if _users == 0:
            zipfile._get_decompressor = _get_decompressor
        _users += 1
    try:
        yield
    finally:
        with _lock:
            _users -= 1
            if _users == 0:
                zipfile._get_decompressor = _original_get_decompressor
