"""Temporary files only: routes cannot start a producer to obtain a frame."""

from __future__ import annotations

import os
import time

import pytest
from flask import Flask

from services.api_core import camera, frames, http_contract, vision_api


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(frames.C, "SNAP_DIR", str(tmp_path))
    monkeypatch.setattr(camera, "_SNAP_DIR_ABS", str(tmp_path))
    monkeypatch.setattr(frames.C, "RAW_PATH", str(tmp_path / "configured.jpg"))
    monkeypatch.setattr(frames.C, "PROC_PATH", str(tmp_path / "proc.jpg"))
    monkeypatch.setattr(frames.C, "SSD_PATH", str(tmp_path / "ssd.jpg"), raising=False)
    app = Flask(__name__)
    http_contract.install(app, after_request=True)
    app.register_blueprint(vision_api.bp)
    app.add_url_rule("/camera/raw", view_func=camera.camera_raw)
    app.add_url_rule("/camera/last", view_func=camera.camera_last)
    app.add_url_rule("/snapshots/<path:fname>", view_func=camera.snapshots_static)
    app.add_url_rule("/camera/placeholder", view_func=camera.camera_placeholder)
    return app.test_client(), tmp_path


def test_resolver_identity_same_file_for_metadata_and_all_raw_aliases(client):
    http, root = client
    (root / "configured.jpg").write_bytes(b"configured JPEG")
    (root / "raw.jpg").write_bytes(b"different JPEG")
    metadata = http.get(
        "/vision/snap-info?light=1", headers={"Accept": "application/vnd.rider.api+json;version=1"}
    ).get_json()
    row = metadata["data"]["raw"]
    assert row["path"] == str(root / "configured.jpg")
    assert row["observed_at"] is None
    assert row["capture_at"] is None
    assert row["file_observed_at"] > 0
    assert row["provenance"] == "file_mtime"
    for alias in ("/camera/raw", "/camera/last", "/vision/cam"):
        image = http.get(alias)
        assert image.status_code == 200
        assert image.data == b"configured JPEG"
        assert image.headers["X-Rider-Frame-Id"] == row["frame_id"]
        assert "X-Rider-Observed-At" not in image.headers
        assert image.headers["X-Rider-File-Observed-At"] == str(row["file_observed_at"])


def test_legacy_metadata_retains_hash_and_light_semantics_without_null_observation(client):
    http, root = client
    (root / "configured.jpg").write_bytes(b"fixture")
    full = http.get("/vision/snap-info").get_json()["raw"]
    light = http.get("/vision/snap-info?light=1").get_json()["raw"]
    assert full["md5"]
    assert light["md5"] is None
    assert "observed_at" not in full
    assert full["mtime"] > 0


@pytest.mark.parametrize("delta,error", [(-10, "frame_stale"), (10, "frame_clock_future")])
def test_current_preview_rejects_bad_time_archive_is_explicit(client, delta, error):
    http, root = client
    file = root / "configured.jpg"
    file.write_bytes(b"historical JPEG")
    at = time.time() + delta
    os.utime(file, (at, at))
    for route in ("/camera/raw", "/camera/last", "/vision/cam"):
        result = http.get(route)
        assert result.status_code == 404
        assert result.get_json()["error"] == error
    result = http.get("/camera/raw?archive=1")
    assert result.status_code == 200
    assert result.headers["X-Rider-Stale"] == "true"


def test_streams_do_not_substitute_ssd_for_obst_and_placeholder_has_no_time(client):
    http, root = client
    (root / "ssd.jpg").write_bytes(b"SSD")
    (root / "obst_annot.jpg").write_bytes(b"OBST")
    assert http.get("/vision/ssd").data == b"SSD"
    assert http.get("/vision/obst").data == b"OBST"
    assert http.get("/vision/obst").headers["X-Rider-Stream"] == "obst"
    placeholder = http.get("/camera/placeholder")
    assert placeholder.headers["X-Rider-Placeholder"] == "true"
    assert "Last-Modified" not in placeholder.headers
