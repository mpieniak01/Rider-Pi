"""Only temporary files and Flask: transfer keeps one captured inode."""

from __future__ import annotations

import os

import pytest
from flask import Flask

from services.api_core import frames


@pytest.fixture
def frame_client(monkeypatch, tmp_path):
    monkeypatch.setattr(frames.time, "time", lambda: 1000.0)
    path = tmp_path / "raw.jpg"
    app = Flask(__name__)
    app.testing = True
    app.add_url_rule("/raw", view_func=lambda: frames.response("raw", path=path), methods=["GET", "HEAD"])
    return app.test_client(), path


def test_atomic_replacement_after_fstat_cannot_change_body_or_headers(frame_client, monkeypatch):
    client, path = frame_client
    original_bytes = b"original captured JPEG"
    path.write_bytes(original_bytes)
    os.utime(path, (999.8, 999.8))
    original_stat = path.stat()
    send_file = frames.send_file
    captured = []

    def replace_before_transfer(handle, **kwargs):
        captured.append(handle)
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(b"new camera JPEG with a different size")
        os.utime(replacement, (1000.0, 1000.0))
        os.replace(replacement, path)
        return send_file(handle, **kwargs)

    monkeypatch.setattr(frames, "send_file", replace_before_transfer)
    result = client.get("/raw")
    assert result.status_code == 200
    assert result.data == original_bytes
    assert result.content_length == len(original_bytes)
    assert result.headers["X-Rider-File-Observed-At"] == str(original_stat.st_mtime)
    assert result.headers["X-Rider-Frame-Id"] == f"raw:{original_stat.st_mtime}:{len(original_bytes)}"
    assert path.read_bytes() != result.data
    result.close()
    assert captured[0].closed


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_source_descriptor_closes_with_response(frame_client, monkeypatch, method):
    client, path = frame_client
    path.write_bytes(b"fixture JPEG")
    os.utime(path, (999.8, 999.8))
    original_send = frames.send_file
    captured = []

    def tracked(handle, **kwargs):
        captured.append(handle)
        return original_send(handle, **kwargs)

    monkeypatch.setattr(frames, "send_file", tracked)
    result = client.open("/raw", method=method)
    assert result.status_code == 200
    assert result.content_length == len(b"fixture JPEG")
    assert result.data == (b"fixture JPEG" if method == "GET" else b"")
    result.close()
    assert captured[0].closed


def test_transfer_failure_closes_owned_descriptor(frame_client, monkeypatch):
    client, path = frame_client
    path.write_bytes(b"fixture JPEG")
    os.utime(path, (999.8, 999.8))
    captured = []

    def failed(handle, **kwargs):
        captured.append(handle)
        raise RuntimeError("isolated transfer failure")

    monkeypatch.setattr(frames, "send_file", failed)
    with pytest.raises(RuntimeError, match="isolated transfer"):
        client.get("/raw")
    assert captured[0].closed


def test_missing_file_remains_not_found(frame_client):
    client, _ = frame_client
    result = client.get("/raw")
    assert result.status_code == 404
    assert result.get_json()["error"] == "frame_not_found"


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_nonregular_file_never_becomes_an_image(frame_client, kind):
    client, path = frame_client
    path.mkdir() if kind == "directory" else os.mkfifo(path)
    result = client.get("/raw?archive=1")
    assert result.status_code == 404
    assert result.get_json()["error"] == "frame_unavailable"


@pytest.mark.parametrize("at,error", [(990.0, "frame_stale"), (1010.0, "frame_clock_future")])
def test_stale_and_future_require_explicit_archive(frame_client, at, error):
    client, path = frame_client
    path.write_bytes(b"historical JPEG")
    os.utime(path, (at, at))
    current = client.get("/raw")
    assert current.status_code == 404
    assert current.get_json()["error"] == error
    archived = client.get("/raw?archive=1")
    assert archived.status_code == 200
    assert archived.data == b"historical JPEG"
    assert archived.headers["X-Rider-Stale"] == "true"
    archived.close()
