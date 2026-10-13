"""Gate/API regressions use fake status and fake BUS exclusively."""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest
from flask import Flask

from services import control_commands as commands, safety_contract as safety


def envelope(action="move", **changes):
    return {
        "action": action,
        "generation": "g",
        "source": "manual",
        "seq": 2,
        "request_id": "fixture-request",
        "ts": time.time(),
        "ttl_ms": 500,
        "duration": 0.1,
        **changes,
    }


@pytest.mark.parametrize("action", ["move", "turn", "height", "balance", "action", "arm", "clear_estop"])
def test_all_actuators_and_arm_require_generation(action):
    payload = envelope(action, operator_consent=True, operator_plan="specific test")
    payload.pop("generation")
    with pytest.raises(ValueError, match="generation"):
        safety.command_envelope(payload)


@pytest.mark.parametrize(
    "key,value",
    [
        ("vx", float("nan")),
        ("yaw", float("inf")),
        ("duration", 2),
        ("ts", float("nan")),
        ("ttl_ms", 1001),
        ("seq", True),
    ],
)
def test_malformed_values_never_publish(key, value):
    with pytest.raises((ValueError, TypeError)):
        safety.command_envelope(envelope(**{key: value}))


def test_arm_needs_plan_and_does_not_stamp_a_delayed_request():
    with pytest.raises(ValueError, match="operator_plan"):
        safety.command_envelope(envelope("arm", operator_consent=True))
    with pytest.raises(ValueError, match="expired"):
        safety.command_envelope(envelope("arm", operator_consent=True, operator_plan="plan", ts=time.time() - 1))


@pytest.mark.parametrize(
    "direction,axis,value",
    [("left", "yaw", -0.1), ("right", "yaw", 0.1), ("forward", "vx", 0.1), ("backward", "vx", -0.1)],
)
def test_aliases_share_direction_convention(direction, axis, value):
    assert commands.normalize_control({"cmd": "move", "dir": direction})[axis] == value


def _fake_publisher(monkeypatch, observation):
    sent = []

    class Publisher:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def publish(self, topic, command):
            sent.append(command)
            observation["last_ack"] = {
                "request_id": command["request_id"],
                "action": command["action"],
                "source": command["source"],
                "seq": command.get("seq"),
                "observed_at": time.time(),
                "status": "executed",
                "accepted": True,
            }

    monkeypatch.setattr(safety, "BusPub", Publisher)
    monkeypatch.setattr(safety, "read_status", lambda: observation)
    return sent


def test_stop_does_not_need_arm_or_metadata(monkeypatch):
    observed = {"state": "DISARMED", "contract_version": 1}
    sent = _fake_publisher(monkeypatch, observed)
    result = safety.request_stop()
    assert result["ok"] and result["confirmed"] and sent[0]["action"] == "stop"
    assert result["physical_completion"] == "unverified"


def test_gateway_forwards_valid_intent_even_without_current_observation(monkeypatch):
    observation = {"state": "UNKNOWN", "contract_version": 1, "stale": True}
    sent = _fake_publisher(monkeypatch, observation)
    result = safety.publish_command(envelope(), timeout_s=0)
    assert sent and sent[0]["generation"] == "g"
    assert result["pending"]  # Only the executor can confirm permission and actuation.


def test_old_successful_ack_cannot_confirm_new_stop(monkeypatch):
    observation = {
        "state": "DISARMED",
        "last_ack": {
            "request_id": "reuse",
            "action": "stop",
            "source": "manual",
            "seq": None,
            "status": "executed",
            "accepted": True,
            "observed_at": time.time() - 1,
        },
    }

    class NoAck:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def publish(self, *args):
            pass

    monkeypatch.setattr(safety, "BusPub", NoAck)
    monkeypatch.setattr(safety, "read_status", lambda: observation)
    result = safety.publish_command({"action": "stop", "request_id": "reuse"}, timeout_s=0)
    assert result["pending"] and not result["confirmed"] and not result["ok"]


def test_goal_accepted_ack_is_still_pending(monkeypatch):
    observation = {
        "state": "ARMED",
        "contract_version": 1,
        "owner": "manual",
        "generation": "g",
        "manual_settings": {"revision": 0},
        "ready": True,
        "can_move": True,
        "capabilities": {"move": {"available": True, "stop_verified": True}},
    }
    _fake_publisher(monkeypatch, observation)
    original = safety.BusPub.publish

    def accepted_only(self, topic, payload):
        original(self, topic, payload)
        observation["last_ack"]["status"] = "accepted"

    monkeypatch.setattr(safety.BusPub, "publish", accepted_only)
    assert safety.publish_command(envelope(settings_revision=0), timeout_s=0)["pending"]


def test_get_with_json_cannot_trigger_actuator(monkeypatch):
    from services.api_core import control_api

    app = Flask(__name__)
    app.add_url_rule("/height", view_func=control_api.api_height, methods=["GET", "POST"])
    monkeypatch.setattr(control_api, "submit_control", lambda _: pytest.fail("GET must not dispatch"))
    assert app.test_client().get("/height", json=envelope("height", height=2)).status_code == 405


def test_unavailable_telemetry_clears_old_data_and_accepts_zero(monkeypatch):
    from services.api_core import devices

    observed = {"roll": 22, "pitch": 30, "yaw": 45, "battery": 88}
    monkeypatch.setattr(devices.C, "LAST_XGO", observed)
    devices._update_xgo_from_dict(
        {"roll": 0, "pitch": 0, "yaw": 0, "battery_pct": None, "observed_at": 123, "ts": 456, "stale": True}
    )
    assert observed["roll"] == observed["pitch"] == observed["yaw"] == 0
    assert observed["battery"] is None and observed["ts"] == 123 and observed["stale"]


def test_manual_probe_rejects_automation_before_http():
    path = Path(__file__).parents[1] / "scripts" / "manual_motion-probe.py"
    spec = importlib.util.spec_from_file_location("manual_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(RuntimeError, match="automated"):
        module.require_operator()


@pytest.mark.parametrize(
    "endpoint,handler", [("start", "api_navigator_start"), ("return_home", "api_navigator_return_home")]
)
def test_direct_navigation_api_refuses_missing_task_journal(monkeypatch, endpoint, handler):
    from apps.navigator import safety as navigation_safety
    from services.api_core import navigator_api

    observed = {
        "contract_version": 1,
        "state": "ARMED",
        "can_move": True,
        "owner": "navigation",
        "generation": "g",
        "last_seq": -1,
    }
    monkeypatch.setattr(navigation_safety, "read_status", lambda: observed)
    monkeypatch.setattr(navigation_safety, "read_service_intent", lambda *args: None)
    monkeypatch.setattr(navigator_api, "read_status", lambda: observed)
    monkeypatch.setattr(
        navigator_api.C, "bus_pub", lambda *args, **kwargs: pytest.fail("missing journal must not dispatch")
    )
    app = Flask(__name__)
    app.add_url_rule("/nav/" + endpoint, view_func=getattr(navigator_api, handler), methods=["POST"])
    response = app.test_client().post("/nav/" + endpoint, json=envelope())
    assert response.status_code == 409
    assert response.get_json()["error"] == "explicit_navigation_task_required"
