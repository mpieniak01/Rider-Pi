"""Bounded navigation trial archive and shared operator history."""

import pytest
from test_navigation_runner import isolated

from apps.compute import navigation as module


def test_terminal_drive_records_frames_and_observation_preserves_shared_outcome(isolated, monkeypatch, tmp_path):
    import hashlib
    import io
    import json
    import zipfile

    from flask import Flask

    from services.api_core import navigation_api

    runner = module.NavigationRunner()
    payload = b"captured-frame"
    runner.frame_trace.append({"data": payload, "captured_at": 1000, "input_id": "capture-1"})
    decision = {"state": "obstacle", "reason": "depth_ground_deviation", "action": "stop"}
    runner.lease.reason = "depth_ground_deviation"
    runner.closed.set()
    runner._status(decision)
    trial = json.loads((tmp_path / "navigation_trial.json").read_text())
    assert trial["run_id"] == runner.run_id and trial["running"] is False
    with zipfile.ZipFile(io.BytesIO((tmp_path / "navigation_trial.zip").read_bytes())) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        frame = manifest["frames"][0]
        assert hashlib.sha256(bundle.read(frame["file"])).hexdigest() == frame["sha256"]
        assert bundle.read(frame["file"]) == payload
        assert manifest["outcome"]["stop_reason"] == "depth_ground_deviation"

    observer = module.NavigationRunner(observe_only=True)
    observer._status({"state": "clear", "vision_action": "go"})
    assert json.loads((tmp_path / "navigation_trial.json").read_text()) == trial
    app = Flask(__name__)
    with app.test_request_context():
        response, status = navigation_api.status_handler()
    row = response.get_json()
    assert status == 200 and row["mode"] == "observe"
    assert row["decision"]["state"] == "clear"
    assert row["last_trial"] == {key: value for key, value in trial.items() if key != "sampled_monotonic"}
    assert not isolated[-1]  # Presentation and recorder never submit a command.


@pytest.mark.parametrize("trial", ["{}", "[]", "not-json", None])
def test_invalid_trial_history_never_changes_current_status(isolated, tmp_path, trial):
    from flask import Flask

    from services.api_core import navigation_api

    if trial is not None:
        (tmp_path / "navigation_trial.json").write_text(trial)
    runner = module.NavigationRunner(observe_only=True)
    runner._status({"state": "clear"})
    with Flask(__name__).test_request_context():
        response, status = navigation_api.status_handler()
    assert status == 200
    assert response.get_json()["last_trial"] is None
    assert response.get_json()["mode"] == "observe"
