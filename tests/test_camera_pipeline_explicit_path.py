"""An explicit file must never borrow fresh RAM metadata."""

import os
import time

import pytest
from flask import Flask

from services import camera_pipeline_store as store
from services.api_core import frames


@pytest.fixture
def file_with_active_ram(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_CAMERA_PIPELINE_CONFIG", str(tmp_path / "pipeline.json"))
    store.write({"contract_version": 1, "revision": 1, "profile": dict(store.DEFAULT_PROFILE)})
    monkeypatch.setattr(frames, "_ram_description", lambda *args: pytest.fail("explicit file borrowed RAM"))
    image = tmp_path / "file.jpg"
    image.write_bytes(b"explicit-file-payload")
    return image


def test_explicit_stale_file_is_not_relabelled_fresh(file_with_active_ram):
    image = file_with_active_ram
    os.utime(image, (1, 1))
    row = frames.describe("raw", path=image, stat_result=image.stat())
    assert row["source"] == "filesystem"
    assert row["stale"] is True
    with Flask(__name__).test_request_context("/camera/raw"):
        result = frames.response("raw", path=image)
        assert result.status_code == 404
        assert result.headers["X-Rider-Stale"] == "true"
        assert result.get_json()["error"] == "frame_stale"


def test_explicit_fresh_file_keeps_its_body_length_and_metadata(file_with_active_ram):
    image = file_with_active_ram
    now = time.time()
    os.utime(image, (now, now))
    with Flask(__name__).test_request_context("/camera/raw"):
        result = frames.response("raw", path=image)
        result.direct_passthrough = False
        assert result.status_code == 200
        assert result.get_data() == image.read_bytes()
        assert result.content_length == image.stat().st_size
        assert result.headers["X-Rider-Source"] == "filesystem"
        result.close()
