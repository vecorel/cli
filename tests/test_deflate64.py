import random
import struct
import zipfile
import zlib

import inflate64
from pytest import mark, raises

from vecorel_cli.conversion.base import BaseConverter
from vecorel_cli.conversion.deflate64 import ZIP_DEFLATED64, deflate64_zip

# Compressible content fits one read; random bytes need many, which exercises the
# streaming decompressor protocol of ZipExtFile.
CONTENTS = {
    "compressible": b"deflate64 " * 20_000,
    "incompressible": random.Random(64).randbytes(2_000_000),
}


def _write_deflate64_zip(path, data, name="member.txt"):
    """A single-member ZIP compressed with Deflate64, which zipfile cannot write."""
    deflater = inflate64.Deflater()
    compressed = deflater.deflate(data) + deflater.flush()
    crc = zlib.crc32(data)
    encoded = name.encode()
    sizes = (crc, len(compressed), len(data), len(encoded))
    local = struct.pack("<4s5H3L2H", b"PK\x03\x04", 21, 0, ZIP_DEFLATED64, 0, 0, *sizes, 0)
    central = struct.pack(
        "<4s6H3L5H2L", b"PK\x01\x02", 21, 21, 0, ZIP_DEFLATED64, 0, 0, *sizes, 0, 0, 0, 0, 0, 0
    )
    offset = len(local) + len(encoded) + len(compressed)
    end = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 1, 1, len(central) + len(encoded), offset, 0)
    path.write_bytes(local + encoded + compressed + central + encoded + end)
    return path


@mark.parametrize("kind", CONTENTS)
def test_zipfile_reads_deflate64_only_inside_the_block(tmp_path, kind):
    archive = _write_deflate64_zip(tmp_path / "a.zip", CONTENTS[kind])
    with raises(NotImplementedError):
        zipfile.ZipFile(archive).read("member.txt")
    with deflate64_zip():
        # read() verifies the CRC, so a truncated or corrupt stream fails here
        assert zipfile.ZipFile(archive).read("member.txt") == CONTENTS[kind]
    with raises(NotImplementedError):
        zipfile.ZipFile(archive).read("member.txt")


def test_overlapping_blocks_restore_zipfile_whatever_order_they_exit_in():
    original = zipfile._get_decompressor
    first, second = deflate64_zip(), deflate64_zip()
    first.__enter__()
    second.__enter__()
    first.__exit__(None, None, None)
    assert zipfile._get_decompressor is not original  # the second block still needs it
    second.__exit__(None, None, None)
    assert zipfile._get_decompressor is original


@mark.parametrize("kind", CONTENTS)
def test_download_files_extracts_deflate64_archives(tmp_path, kind):
    archive = _write_deflate64_zip(tmp_path / "source.zip", CONTENTS[kind])
    paths = BaseConverter().download_files(
        {str(archive): ["member.txt"]}, cache_folder=str(tmp_path / "cache")
    )
    assert len(paths) == 1
    with open(paths[0][0], "rb") as f:
        assert f.read() == CONTENTS[kind]
