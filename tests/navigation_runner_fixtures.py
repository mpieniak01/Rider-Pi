"""Inert authority, executor and command fixture for navigation runner tests."""

import pytest

from apps.compute import navigation as module
from services.navigation_config import DEFAULT


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    policy = {**DEFAULT, "mode": "drive", "verified": True, "calibration_id": "trial", "model_sha256": "a" * 64}
    selection = {
        "id": "venom",
        "revision": 1,
        "device_id": "pi",
        "token": "fixture-token",
        "url": "http://127.0.0.1:8800",
        "tasks": [],
    }
    safety = {
        "remote_decision_deadline_supported": True,
        "remote_decision_feedback_supported": True,
        "scoped_stop_generation_supported": True,
        "can_move": True,
        "owner": "navigation",
        "generation": "gen",
        "last_seq": 0,
        "manual_settings": {"revision": 3},
        "calibration": {"profile_digest": "accepted"},
    }
    intent = {"generation": "gen", "request_id": "intent", "seq": 1, "settings_revision": 3}
    commands = []
    monkeypatch.setattr(module.navigation_config, "snapshot", lambda: dict(policy))
    monkeypatch.setattr(module, "selected_executor", lambda: dict(selection))
    monkeypatch.setattr(module, "read_status", lambda: dict(safety))
    monkeypatch.setattr(module, "read_service_intent", lambda *_: dict(intent))
    monkeypatch.setattr(module, "write_intent_status", lambda *a, **kw: True)
    monkeypatch.setenv("RIDER_NAVIGATION_STATUS", str(tmp_path / "status.json"))

    def submit(data, **_kwargs):
        commands.append(data)
        return {"ok": True}, 200

    class Publisher:
        def close(self):
            pass

    monkeypatch.setattr(module, "BusPub", lambda **_kwargs: Publisher())
    monkeypatch.setattr(module, "submit_control", submit)
    return policy, selection, safety, intent, commands
