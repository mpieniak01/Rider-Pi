"""CLI uses an operator supplied envelope; fixtures never start real units."""

import json
from types import SimpleNamespace

from scripts import robot_ctl


def test_moving_start_without_tty_never_constructs_manager(monkeypatch):
    monkeypatch.setattr(robot_ctl.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(robot_ctl, "FeatureManager", lambda: (_ for _ in ()).throw(AssertionError("manager opened")))
    assert robot_ctl.main(["start", "recon"]) == 2


def test_moving_start_without_file_is_explicitly_unavailable(monkeypatch):
    monkeypatch.setattr(robot_ctl.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    assert robot_ctl.main(["start", "s9_navigation"]) == 2


def test_manual_control_file_is_passed_without_restamp(monkeypatch, tmp_path):
    calls = []
    envelope = {"generation": "generation", "request_id": "manual", "seq": 7, "ts": 100, "ttl_ms": 500}
    path = tmp_path / "control.json"
    path.write_text(json.dumps(envelope))
    monkeypatch.setattr(robot_ctl.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(
        robot_ctl,
        "FeatureManager",
        lambda: SimpleNamespace(
            set_feature=lambda *a, **kw: calls.append((a, kw))
            or {"ok": False, "error": "stale_or_invalid_operator_intent"}
        ),
    )
    assert robot_ctl.main(["start", "recon", "--control-file", str(path)]) == 1
    assert calls == [(("recon", True), {"control": envelope})]


def test_invalid_control_file_never_constructs_manager(monkeypatch, tmp_path):
    path = tmp_path / "control.json"
    path.write_text("[]")
    monkeypatch.setattr(robot_ctl.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(robot_ctl, "FeatureManager", lambda: (_ for _ in ()).throw(AssertionError("manager opened")))
    assert robot_ctl.main(["start", "recon", "--control-file", str(path)]) == 2


def test_stop_needs_no_operator_file(monkeypatch):
    calls = []
    monkeypatch.setattr(
        robot_ctl,
        "FeatureManager",
        lambda: SimpleNamespace(set_feature=lambda *a, **kw: calls.append((a, kw)) or {"ok": True}),
    )
    assert robot_ctl.main(["stop", "recon"]) == 0
    assert calls == [(("recon", False), {"control": None})]
