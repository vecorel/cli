import pytest

import vecorel_cli.conversion.base as base
from vecorel_cli.conversion.base import BaseConverter

URI = "https://example.invalid/data/fields.gml"


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
