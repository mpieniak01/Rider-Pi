from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts.camera_recovery import recover
from services.api_core import features_api, resource_diag


@pytest.mark.parametrize("path", ["/dev/spidev0.0", "/dev/fb1", "/dev/video0-extra"])
def test_camera_helper_cannot_touch_other_device(path):
    assert recover([path], [123], force=True, operator_consent=True)["error"] == "exact_v4l2_paths_required"


def test_helper_requires_confirmed_exact_owner(monkeypatch):
    monkeypatch.setattr(
        resource_diag,
        "inspect",
        lambda _: {
            "state": "busy",
            "holders": [{"pid": 123, "path": "/dev/video1", "service": "camera-capture@raw.service"}],
        },
    )
    assert recover(["/dev/video0"], [123], force=True, operator_consent=True)["error"] == "owner_mismatch_or_protected"
    assert (
        recover(["/dev/video1"], [123], force=False, operator_consent=True)["error"]
        == "manual_recovery_confirmation_required"
    )


@pytest.mark.parametrize("rc,output", [(0, ""), (1, "p123\0n/dev/video0\0"), (0, "p123\0cpython\0")])
def test_malformed_lsof_is_unknown_not_free(monkeypatch, rc, output):
    monkeypatch.setattr(resource_diag, "_existing_paths", lambda _: ["/dev/video0"])
    monkeypatch.setattr(
        resource_diag.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=rc, stdout=output, stderr=""),
    )
    observed = resource_diag.inspect("camera")
    assert observed["state"] == "unknown"
    assert observed["free"] is None


def test_maintenance_cli_respects_recorded_api_task_consumer(monkeypatch, tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"resource_consumers": {"camera": ["s6_tracker_module"]}}))
    monkeypatch.setattr(features_api.feature_manager, "_state_path", path)
    monkeypatch.setattr(features_api.feature_manager, "resource_consumers", lambda: {})
    monkeypatch.setattr(
        resource_diag,
        "inspect",
        lambda _: {
            "state": "busy",
            "holders": [{"pid": 123, "path": "/dev/video0", "service": "camera-capture@raw.service"}],
        },
    )
    assert recover(["/dev/video0"], [123], force=True, operator_consent=True)["error"] == "ownership_unknown_or_in_use"


def test_corrupt_consumer_journal_blocks_manual_release(monkeypatch, tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not JSON")
    monkeypatch.setattr(features_api.feature_manager, "_state_path", path)
    monkeypatch.setattr(resource_diag, "inspect", lambda _: {"state": "busy", "holders": []})
    assert (
        resource_diag.release("camera", limit_pids=[123], force=True, operator_consent=True)["error"]
        == "task_ownership_unknown"
    )
