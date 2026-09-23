import io

import multivolumefile
import py7zr
import pytest
from fsspec.implementations.local import LocalFileSystem

import vecorel_cli.conversion.base as base
from vecorel_cli.conversion.base import BaseConverter
from vecorel_cli.vecorel.util import stream_file

URI = "https://example.invalid/data/fields.gml"


class _FakeStreamFile:
    """Minimal stand-in for an fsspec HTTP streaming file: yields ``data`` and
    exposes the response headers on ``.r.headers`` like ``HTTPStreamFile``."""

    def __init__(self, data, headers):
        self._buf = io.BytesIO(data)
        self.r = type("_Resp", (), {"headers": headers})()

    def read(self, size=-1):
        return self._buf.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._buf.close()
        return False


class _FakeSourceFS:
    def __init__(self, data, headers):
        self._data = data
        self._headers = headers

    def open(self, src_uri, mode="rb", block_size=0, **kwargs):
        return _FakeStreamFile(self._data, self._headers)


def test_failed_download_leaves_no_cache_file(tmp_folder, monkeypatch):
    """A download that raises must not leave a file behind that a later run
    would treat as cached (#43)."""

    def failing_stream(fs, src_uri, dst_file, chunk_size=None):
        dst_file.write(b"partial")
        raise RuntimeError("403 Forbidden")

    monkeypatch.setattr(base, "stream_file", failing_stream)

    with pytest.raises(RuntimeError, match="403"):
        BaseConverter().download_files(URI, cache_folder=str(tmp_folder))

    assert list(tmp_folder.iterdir()) == [], "cache must be empty after a failed download"


def test_failed_download_is_retried_on_next_run(tmp_folder, monkeypatch):
    calls = []

    def stream(fs, src_uri, dst_file, chunk_size=None):
        calls.append(src_uri)
        if len(calls) == 1:
            raise RuntimeError("timeout")
        dst_file.write(b"<gml/>")

    monkeypatch.setattr(base, "stream_file", stream)

    with pytest.raises(RuntimeError):
        BaseConverter().download_files(URI, cache_folder=str(tmp_folder))

    paths = BaseConverter().download_files(URI, cache_folder=str(tmp_folder))

    assert len(calls) == 2, "the second run must download again"
    assert paths == [(str(tmp_folder / "fields.gml"), URI)]
    assert (tmp_folder / "fields.gml").read_bytes() == b"<gml/>"
    assert not (tmp_folder / "fields.gml.part").exists()


def test_successful_download_is_cached(tmp_folder, monkeypatch):
    calls = []

    def stream(fs, src_uri, dst_file, chunk_size=None):
        calls.append(src_uri)
        dst_file.write(b"<gml/>")

    monkeypatch.setattr(base, "stream_file", stream)

    BaseConverter().download_files(URI, cache_folder=str(tmp_folder))
    BaseConverter().download_files(URI, cache_folder=str(tmp_folder))

    assert calls == [URI], "a completed download must be reused"


def test_stream_file_rejects_truncated_response():
    """A body shorter than the promised Content-Length is a failed download (#46)."""
    fs = _FakeSourceFS(b"partial", {"Content-Length": "2823630848"})
    dst = io.BytesIO()
    with pytest.raises(OSError, match="Incomplete download"):
        stream_file(fs, URI, dst)


def test_stream_file_accepts_matching_content_length():
    body = b"complete body"
    fs = _FakeSourceFS(body, {"Content-Length": str(len(body))})
    dst = io.BytesIO()
    stream_file(fs, URI, dst)
    assert dst.getvalue() == body


def test_stream_file_skips_check_for_compressed_response():
    """A compressed body is decoded while streaming, so the decoded byte count
    legitimately differs from the compressed Content-Length; no false failure."""
    body = b"decoded payload longer than the header"
    fs = _FakeSourceFS(body, {"Content-Length": "5", "Content-Encoding": "gzip"})
    dst = io.BytesIO()
    stream_file(fs, URI, dst)
    assert dst.getvalue() == body


def test_stream_file_without_content_length_is_accepted():
    body = b"chunked body of unknown length"
    fs = _FakeSourceFS(body, {})
    dst = io.BytesIO()
    stream_file(fs, URI, dst)
    assert dst.getvalue() == body


def test_truncated_download_is_not_cached(tmp_folder, monkeypatch):
    """A truncated download must not be promoted into the cache where a later run
    would treat it as a complete file (#46)."""
    source_fs = _FakeSourceFS(b"partial", {"Content-Length": "999"})

    def fake_get_fs(uri, **kwargs):
        if str(uri).startswith(("http://", "https://")):
            return source_fs
        return LocalFileSystem()

    monkeypatch.setattr(base, "get_fs", fake_get_fs)

    with pytest.raises(OSError, match="Incomplete download"):
        BaseConverter().download_files(URI, cache_folder=str(tmp_folder))

    assert list(tmp_folder.iterdir()) == [], "a truncated download must not be cached"


@pytest.mark.parametrize("explicit_cache", [True, False])
def test_multivolume_7z_is_downloaded_and_extracted(explicit_cache, tmp_folder, monkeypatch):
    """Multi-volume 7z archives (.7z.001, .7z.002, ...) are one 7z stream split
    across several URIs; the parts must be fetched and extracted together, with
    the target paths taken from whichever part carries them. Works with an
    explicit cache folder and with the default temporary one."""
    arcname = "nested/PARCELLES.gpkg"
    payload = b"crop fields payload " * 200

    # a real multi-volume 7z that the fake download server will serve part by part;
    # size the volumes off the whole archive so it always spans about three parts
    measure = io.BytesIO()
    with py7zr.SevenZipFile(measure, "w") as sz_file:
        sz_file.writestr(payload, arcname)
    volume_size = len(measure.getvalue()) // 3 + 1

    source = tmp_folder / "source"
    source.mkdir()
    with multivolumefile.MultiVolume(
        str(source / "data.7z"), mode="wb", volume=volume_size, ext_digits=3
    ) as volume:
        with py7zr.SevenZipFile(volume, "w") as sz_file:
            sz_file.writestr(payload, arcname)
    parts = sorted(p.name for p in source.iterdir())
    assert len(parts) > 1, "the payload must span several volumes for this test"

    def stream(fs, src_uri, dst_file, chunk_size=None):
        dst_file.write((source / src_uri.rsplit("/", 1)[-1]).read_bytes())

    monkeypatch.setattr(base, "stream_file", stream)

    base_url = "https://example.invalid/rpg/data.7z"
    # only the first part names the target file, the rest carry the empty list
    uris = {f"{base_url}.{i:03d}": ([arcname] if i == 1 else []) for i in range(1, len(parts) + 1)}

    cache_folder = str(tmp_folder) if explicit_cache else None
    paths = BaseConverter().download_files(uris, cache_folder=cache_folder)

    assert len(paths) == 1
    extracted, uri = paths[0]
    assert uri == f"{base_url}.001", "the source is reported as the first volume"
    with open(extracted, "rb") as f:
        assert f.read() == payload
    if explicit_cache:
        # every volume was cached under its own name
        for part in parts:
            assert (tmp_folder / part).exists()
