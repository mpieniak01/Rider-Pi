"""Adversarial safety inputs use the existing fake executor and no physical I/O."""

from __future__ import annotations

import time
from unittest.mock import Mock

import pytest
from flask import Flask, Response
from motion_fakes import arm, command, executor as executor

from apps.safety import state
from services import safety_contract as contract
from services.api_core import http_security


@pytest.fixture(autouse=True)
def snapshot_path(monkeypatch, tmp_path):
    """Every state read/write stays inside its own temporary test directory."""
    monkeypatch.setenv("MOTION_STATE_PATH", str(tmp_path / "snapshot.json"))


@pytest.mark.parametrize("field", ["ts", "vx", "yaw", "duration"])
def test_api_numeric_overflow_is_a_validation_error(field):
    """A bounded JSON integer must not escape the public validation boundary."""
    payload = {
        "action": "move",
        "source": "manual",
        "request_id": "overflow",
        "generation": "g",
        "seq": 1,
        "ts": time.time(),
        "ttl_ms": 500,
        field: 10**400,
    }
    with pytest.raises(ValueError, match=field):
        contract.command_envelope(payload)


@pytest.mark.parametrize(
    "value", [10**400, -(10**400), "1000", [], {}], ids=["huge", "negative", "text", "list", "object"]
)
def test_executor_timestamp_rejection_preserves_authority(executor, value):
    """Malformed timestamps cannot throw out of authorization or consume a sequence."""
    instance, _ = executor
    arm(instance)
    before = list(instance.adapter.calls)
    seq = instance.gate.last_seq
    accepted, reason = instance.gate.authorize(command(instance, ts=value))
    assert accepted is False
    assert reason == "timestamp_required"
    assert instance.gate.last_seq == seq
    assert instance.adapter.calls == before


@pytest.mark.parametrize("value", [10**400, -(10**400)], ids=["huge", "negative"])
def test_executor_lease_overflow_is_rejected_without_arming(executor, value):
    """Overflow during lease conversion is a normal rejection, not a crashed executor."""
    instance, _ = executor
    accepted, reason = instance.gate.authorize(
        command(
            instance,
            "arm",
            operator_consent=True,
            operator_plan="Isolated fake gate",
            lease_s=value,
        )
    )
    assert accepted is False
    assert reason == "invalid_lease"
    assert instance.gate.state == "DISARMED"


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("source", [], "invalid command source"),
        ("owner", {}, "invalid owner"),
        ("direction", [], "manual_direction"),
    ],
)
def test_api_structured_metadata_is_rejected_as_validation(field, value, reason):
    """Unhashable JSON containers must not leak TypeError from enum membership."""
    payload = {
        "action": "arm" if field == "owner" else "move",
        "source": "manual",
        "request_id": "types",
        "generation": "g",
        "seq": 1,
        "ts": time.time(),
        "ttl_ms": 500,
        "operator_consent": True,
        "operator_plan": "Isolated test",
        field: value,
    }
    if field == "direction":
        payload["device_settings"] = True
    with pytest.raises(ValueError, match=reason):
        contract.command_envelope(payload)


@pytest.mark.parametrize("change", [{"contract_version": True}, {"observed_at": "1000"}, {"observed_at": True}])
def test_snapshot_rejects_boolean_version_and_non_numeric_observation(monkeypatch, change):
    """Unknown or wrongly typed evidence never becomes a fresh execution claim."""
    monkeypatch.setattr(state.time, "time", lambda: 1000)
    state.write_status(
        {
            "contract_version": 1,
            "state": "ARMED",
            "observed_at": 1000,
            "ready": True,
            "hardware_ready": True,
            "can_move": True,
            "lease_remaining_s": 5,
            **change,
        }
    )
    result = state.read_status()
    assert result["state"] == "UNKNOWN"
    assert result["can_move"] is False


@pytest.mark.parametrize("max_age", [float("nan"), float("inf"), -1, True])
def test_snapshot_invalid_freshness_policy_fails_closed(monkeypatch, max_age):
    """NaN cannot turn the freshness comparison into an unlimited permission."""
    monkeypatch.setattr(state.time, "time", lambda: 1000)
    state.write_status(
        {
            "contract_version": 1,
            "state": "ARMED",
            "observed_at": 1000,
            "ready": True,
            "hardware_ready": True,
            "can_move": True,
            "lease_remaining_s": 5,
        }
    )
    assert state.read_status(max_age_s=max_age)["state"] == "UNKNOWN"


@pytest.mark.parametrize(
    "change",
    [
        {"observed_at": float("inf")},
        {"observed_at": float("nan")},
        {"observed_at": 10**400},
        {"seq": True},
        {"status": "executed", "accepted": False},
        {"status": "rejected", "accepted": True},
    ],
)
def test_malformed_ack_never_confirms_a_command(monkeypatch, change):
    """Terminal evidence must be finite, typed and internally consistent."""
    submitted = {"action": "move", "request_id": "ack", "source": "manual", "seq": 1, "generation": "g"}
    ack = {
        **submitted,
        "command_generation": "g",
        "observed_at": 1000,
        "status": "executed",
        "accepted": True,
        **change,
    }
    monkeypatch.setattr(contract, "read_status", lambda: {"last_ack": ack})
    result = contract._await_ack(submitted, 1000, 0)
    assert result["pending"] is True
    assert result["confirmed"] is False


@pytest.mark.parametrize("candidate", [None, "noise", []])
def test_malformed_recent_ack_does_not_hide_later_valid_evidence(monkeypatch, candidate):
    """A bad cache entry cannot stop matching a valid later acknowledgement."""
    submitted = {"action": "stop", "request_id": "ack", "source": "manual"}
    ack = {**submitted, "observed_at": 1000, "status": "executed", "accepted": True}
    monkeypatch.setattr(contract, "read_status", lambda: {"recent_acks": [candidate, ack]})
    result = contract._await_ack(submitted, 1000, 0)
    assert result["confirmed"] is True
    assert result["ok"] is True


def test_cors_removes_all_adjacent_legacy_grants():
    """Header removal must iterate a snapshot, not skip entries in the live iterable."""
    app = Flask(__name__)
    response = Response(
        "fixture",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Credentials": "true",
            "X-Fixture": "keep",
        },
    )
    with app.test_request_context(headers={"Origin": "https://untrusted.invalid"}):
        http_security.apply_cors(response)
    assert not any(key.lower().startswith("access-control-") for key in response.headers.keys())
    assert response.headers["X-Fixture"] == "keep"


@pytest.mark.parametrize("action", [[], {}, None, True])
def test_safety_route_rejects_structured_action_without_dispatch(monkeypatch, action):
    """Malformed actions get HTTP 400 before entering the shared command path."""
    from services.api_core import control_api

    submit = Mock()
    monkeypatch.setattr(control_api, "submit_control", submit)
    app = Flask(__name__)
    app.add_url_rule("/api/safety", view_func=control_api.api_safety, methods=["POST"])
    response = app.test_client().post("/api/safety", json={"action": action})
    assert response.status_code == 400
    submit.assert_not_called()


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"panel_id": [], "generation": "stale"}, "invalid_panel_id"),
        ({"generation": "stale", "seq": -1}, "stale_generation"),
        ({"seq": -1, "ts": 900}, "stale_sequence"),
        ({"ts": 900, "execution_context": "invalid"}, "expired_command"),
    ],
)
def test_ordered_rejections_do_not_consume_sequence(executor, changes, expected):
    """Refactoring cannot change which safety barrier rejects a malformed command first."""
    instance, _ = executor
    arm(instance)
    sequence = instance.gate.last_seq
    result = instance.gate.authorize(command(instance, **changes))
    assert result == (False, expected)
    assert instance.gate.last_seq == sequence
