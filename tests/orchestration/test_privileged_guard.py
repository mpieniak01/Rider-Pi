from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from common import service_action_guard, systemd_ctrl


@pytest.fixture
def safety(monkeypatch):
    value = {
        "ready": True,
        "can_move": True,
        "owner": "follow_me",
        "generation": "current",
        "capabilities": {name: {"available": True, "stop_verified": True} for name in ("move", "turn")},
    }
    module = ModuleType("services.safety_contract")
    module.read_status = lambda: value
    module.request_stop = lambda: {"ok": True, "confirmed": True}
    monkeypatch.setitem(sys.modules, "services.safety_contract", module)
    return value


def test_sole_executor_baseline_start_does_not_arm():
    assert service_action_guard.check("motion-executor.service", "start")["effects"] == [
        "read_only_disarmed_executor_start"
    ]


def test_privileged_moving_start_requires_matching_written_intent(tmp_path, monkeypatch, safety):
    path = tmp_path / "state.json"
    monkeypatch.setenv("FEATURE_STATE_PATH", str(path))
    assert not service_action_guard.check("rider-tracking-controller.service", "start")["ok"]
    path.write_text(
        json.dumps(
            {
                "service_intents": {
                    "rider-tracking-controller.service": {"generation": "current", "request_id": "explicit-click"}
                }
            }
        )
    )
    assert service_action_guard.check("rider-tracking-controller.service", "start")["ok"]
    safety["generation"] = "new-arm"
    assert not service_action_guard.check("rider-tracking-controller.service", "start")["ok"]


def test_privileged_restart_never_rearms(tmp_path, monkeypatch, safety):
    monkeypatch.setattr(service_action_guard, "_intent", lambda unit: {"generation": "current", "request_id": "click"})
    assert not service_action_guard.check("rider-tracking-controller.service", "restart")["ok"]


def test_privileged_stop_requires_confirmation(monkeypatch, safety):
    module = sys.modules["services.safety_contract"]
    monkeypatch.setattr(module, "request_stop", lambda: {"ok": True, "confirmed": False})
    assert not service_action_guard.check("motion-executor.service", "stop")["ok"]


def test_systemctl_fallback_cannot_bypass_guard(monkeypatch, tmp_path, safety):
    monkeypatch.setattr(systemd_ctrl, "SERVICE_CTL", tmp_path / "missing")
    monkeypatch.setattr(service_action_guard, "_intent", lambda unit: {})
    result = systemd_ctrl.run_unit_action("rider-tracking-controller.service", "start")
    assert result.method == "unavailable" and not result.ok


def test_passive_service_uses_installed_shared_backend(monkeypatch, tmp_path):
    backend = tmp_path / "backend"
    backend.write_text("")
    backend.chmod(0o755)
    monkeypatch.setattr(systemd_ctrl, "SERVICE_CTL", backend)
    calls = []
    monkeypatch.setattr(
        systemd_ctrl.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    assert systemd_ctrl.run_unit_action("camera-capture@raw.service", "start").ok
    assert calls == [["sudo", "-n", str(backend), "camera-capture@raw.service", "start"]]
