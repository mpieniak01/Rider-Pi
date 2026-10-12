"""Public CLI preserves operator intent and never opens hardware in fixtures."""

import json
from types import SimpleNamespace

import pytest

from scripts import robot_ctl


@pytest.fixture
def client(monkeypatch):
    calls = []
    value = SimpleNamespace(requested=False)

    def catalog():
        return {
            "features": [
                {"name": "s9_navigation", "aliases": ["recon"], "can_move": True},
                {"name": "s2_camera_preview", "aliases": ["preview"], "can_move": False, "requested": value.requested},
            ]
        }

    def request(path, method="GET", body=None):
        calls.append((path, method, body))
        return {"ok": True, "data": {"result": {"ok": True}}}

    fake = SimpleNamespace(catalog=catalog, request=request)
    monkeypatch.setattr(robot_ctl, "APIClient", lambda *args: fake)
    return calls, value


@pytest.mark.parametrize("tty,file", [(False, None), (True, None)])
def test_moving_start_requires_operator(monkeypatch, client, tty, file):
    monkeypatch.setattr(robot_ctl.sys, "stdin", SimpleNamespace(isatty=lambda: tty))
    assert robot_ctl.main(["start", "recon"]) == 1
    assert not client[0]


def test_manual_control_file_is_passed_without_restamp(monkeypatch, tmp_path, client):
    envelope = {"generation": "generation", "request_id": "manual", "seq": 7, "ts": 100, "ttl_ms": 500}
    path = tmp_path / "control.json"
    path.write_text(json.dumps(envelope))
    monkeypatch.setattr(robot_ctl.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    assert robot_ctl.main(["start", "recon", "--control-file", str(path)]) == 0
    assert client[0] == [("/api/logic/feature/recon", "POST", {**envelope, "enabled": True, "options": {}})]


def test_invalid_control_file_never_mutates(monkeypatch, tmp_path, client):
    path = tmp_path / "control.json"
    path.write_text("[]")
    monkeypatch.setattr(robot_ctl.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    assert robot_ctl.main(["start", "recon", "--control-file", str(path)]) == 1
    assert not client[0]


def test_stop_needs_no_operator_file(client):
    assert robot_ctl.main(["stop", "recon"]) == 0
    assert client[0] == [("/api/logic/feature/recon", "POST", {"enabled": False, "options": {}})]


def test_timed_session_cannot_stop_existing_goal(client):
    client[1].requested = True
    assert robot_ctl.main(["start", "preview", "--seconds", "1"]) == 1
    assert not client[0]


def test_timed_moving_session_is_forbidden(monkeypatch, tmp_path, client):
    path = tmp_path / "control.json"
    path.write_text("{}")
    monkeypatch.setattr(robot_ctl.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    assert robot_ctl.main(["start", "recon", "--control-file", str(path), "--seconds", "1"]) == 1
    assert not client[0]
