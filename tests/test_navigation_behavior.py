"""Profiles and SLOW are tested against real policy/lease, without hardware."""

from copy import deepcopy

import pytest

from apps.compute.decision_lease import DecisionLease
from services import navigation_config, safety_contract
from services.navigation_profiles import DEFAULT_BEHAVIOR, catalog, parameters, policy_digest, validate_behavior


def stopped():
    return {
        "state": "ARMED",
        "ready": True,
        "stale": False,
        "moving": False,
        "target": {"lx": 0, "az": 0},
        "output": {"lx": 0, "az": 0},
    }


@pytest.fixture
def policy_store(tmp_path, monkeypatch):
    monkeypatch.setenv("RIDER_NAVIGATION_CONFIG", str(tmp_path / "navigation.json"))
    monkeypatch.setattr(navigation_config, "_require_idle_goals", lambda: None)
    monkeypatch.setattr(navigation_config, "_require_navigation_goals_stopped", lambda: None)
    monkeypatch.setattr(safety_contract, "read_status", lambda **_: stopped())


def behavior(name="balanced"):
    return {**DEFAULT_BEHAVIOR, "profile_id": name}


def test_select_profile_forces_observation_and_invalidates_approval(policy_store):
    old = navigation_config.snapshot()
    result = navigation_config.configure(
        {
            "revision": old["revision"],
            "values": {
                "behavior": behavior(),
                "mode": "drive",
                "verified": True,
                "calibration_id": "forged",
                "model_sha256": "a" * 64,
            },
        }
    )
    assert result["behavior"] == behavior()
    assert result["mode"] == "observe" and result["verified"] is False
    assert result["calibration_id"] == result["model_sha256"] == ""
    assert result["avoidance"]["sweep_verified"] is False
    with pytest.raises(ValueError, match="conflict"):
        navigation_config.configure({"revision": 0, "values": {"behavior": behavior("fluid")}})


@pytest.mark.parametrize(
    "field,value",
    [("moving", True), ("stale", True), ("ready", False), ("output", {"lx": 0.01, "az": 0}), ("target", None)],
)
def test_profile_change_rejected_while_moving_or_unknown(policy_store, monkeypatch, field, value):
    state = stopped()
    state[field] = value
    monkeypatch.setattr(safety_contract, "read_status", lambda **_: state)
    with pytest.raises(ValueError, match="requires_stopped"):
        navigation_config.configure({"revision": 0, "values": {"behavior": behavior()}})
    assert navigation_config.snapshot()["revision"] == 0


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"version": True, "profile_id": "fluid", "profile_revision": 1},
        {"version": 1, "profile_id": "fluid", "profile_revision": True},
        {**behavior(), "speed_factor": 9},
        behavior("anything"),
    ],
)
def test_profile_wire_is_strict(value):
    with pytest.raises(ValueError, match="behavior_invalid"):
        validate_behavior(value)


def setup():
    config = deepcopy(navigation_config.DEFAULT)
    config.update(mode="drive", verified=True, calibration_id="accepted", model_sha256="a" * 64, behavior=behavior())
    calls, now = [], [0.0]
    lease = DecisionLease(
        config,
        "run",
        lambda *args: calls.append(("drive", *args)),
        lambda: calls.append(("stop",)),
        lambda: now[0],
        pause=lambda value: calls.append(("zero", value)),
        feedback_wait=True,
    )
    return config, lease, calls, now


def reply(config, sequence=1, action="slow"):
    return {
        "protocol_version": 1,
        "run_id": "run",
        "frame_id": "f" + str(sequence),
        "sequence": sequence,
        "config_revision": config["revision"],
        "model_sha256": "a" * 64,
        "clear_count": 3,
        "valid_for_ms": 150,
        "state": "unknown" if action == "slow" else "clear",
        "action": action,
        "behavior": config["behavior"],
        "effective_policy_sha256": policy_digest(config["behavior"]),
        "temporal": {
            "version": 1,
            "action": action,
            "risk": "caution" if action == "slow" else "clear",
            "near_guard_clear": True,
            "evidence_frames": 3,
            "speed_factor": parameters(config["behavior"])["slow_speed_factor"] if action == "slow" else 1,
        },
    }


def test_slow_uses_lower_speed_and_original_pulse_deadline():
    config, lease, calls, now = setup()
    assert lease.accept(reply(config), "f1", 1, 0)
    assert calls == [("drive", 0.05, 0.15)]
    assert lease.deadline == 0.15
    now[0] = 0.31
    assert not lease.tick()
    assert calls[-1] == ("stop",)
    assert not lease.accept(reply(config, 2, "go"), "f2", 2, 0.31)


@pytest.mark.parametrize(
    "change",
    [
        {"effective_policy_sha256": "b" * 64},
        {"behavior": behavior("fluid")},
        {
            "temporal": {
                "version": 1,
                "action": "slow",
                "risk": "caution",
                "near_guard_clear": False,
                "evidence_frames": 3,
                "speed_factor": 0.5,
            }
        },
        {
            "temporal": {
                "version": 1,
                "action": "slow",
                "risk": "caution",
                "near_guard_clear": True,
                "evidence_frames": 3,
                "speed_factor": 0.8,
            }
        },
        {
            "temporal": {
                "version": 1,
                "action": "slow",
                "risk": "caution",
                "near_guard_clear": True,
                "evidence_frames": 2,
                "speed_factor": 0.5,
            }
        },
        {"clear_count": 2},
        {"valid_for_ms": 0},
    ],
)
def test_forged_or_unqualified_slow_never_reaches_drive(change):
    config, lease, calls, _ = setup()
    assert not lease.accept({**reply(config), **change}, "f1", 1, 0)
    assert not any(c[0] == "drive" for c in calls)


def test_observation_and_legacy_cannot_actuate_slow():
    for mode, selected in [("observe", behavior()), ("drive", behavior("legacy"))]:
        config, lease, calls, _ = setup()
        request = reply(config)
        config.update(mode=mode, behavior=selected)
        lease.config = config
        assert not lease.accept(request, "f1", 1, 0)
        assert not any(c[0] == "drive" for c in calls)


def test_catalog_does_not_return_mutable_policy_globals():
    first = catalog(behavior())
    first["profiles"][2]["parameters"]["slow_speed_factor"] = 100
    assert parameters(behavior())["slow_speed_factor"] == 0.5
    assert len({policy_digest(behavior(name)) for name in ["legacy", "cautious", "balanced", "fluid"]}) == 4


def test_profile_stopped_check_and_atomic_write_share_executor_lock(policy_store, monkeypatch):
    from contextlib import contextmanager

    from apps.motion import manual_settings

    held = []
    original_write = navigation_config._write

    @contextmanager
    def executor(*, blocking):
        assert blocking is False
        held.append(True)
        try:
            yield
        finally:
            held.pop()

    def status(**_):
        assert held == [True]
        return stopped()

    def write(*args):
        assert held == [True]
        return original_write(*args)

    monkeypatch.setattr(manual_settings, "locked", executor)
    monkeypatch.setattr(safety_contract, "read_status", status)
    monkeypatch.setattr(navigation_config, "_write", write)
    navigation_config.configure({"revision": 0, "values": {"behavior": behavior()}})
    assert not held


def test_profile_busy_is_conflict_and_does_not_persist(policy_store, monkeypatch):
    from flask import Flask

    from services.api_core.navigation_api import config_handler

    def busy(_):
        raise BlockingIOError("manual_settings_busy")

    monkeypatch.setattr(navigation_config, "configure", busy)
    with Flask(__name__).test_request_context(method="POST", json={"revision": 0}):
        response, code = config_handler()
        assert code == 409 and response.get_json()["error"] == "navigation_profile_busy"
    assert navigation_config.snapshot()["revision"] == 0


@pytest.mark.parametrize("status", [{}, {"temporal_navigation_v1": False}, {"temporal_navigation_v1": 1}])
def test_missing_pair_capability_blocks_preflight(status):
    from apps.compute.client import ComputeError
    from apps.compute.stream_prepare import _require_temporal

    with pytest.raises(ComputeError, match="temporal_navigation_update_required"):
        _require_temporal(status, 1)
    _require_temporal(status, None)  # Existing legacy hosts are unchanged.


def test_exact_pair_capability_is_accepted_without_actuation():
    from apps.compute.stream_prepare import _require_temporal

    _require_temporal({"temporal_navigation_v1": True}, 1)


@pytest.mark.parametrize(
    "received",
    [
        {**DEFAULT_BEHAVIOR, "profile_id": "fluid"},
        {"profile_id": "legacy"},
        None,
    ],
)
def test_legacy_rejects_replies_explicitly_using_another_profile(received):
    from services.navigation_behavior import reply_valid

    assert not reply_valid({"behavior": DEFAULT_BEHAVIOR}, {"action": "go", "state": "clear", "behavior": received})


def test_legacy_keeps_old_wire_and_correct_explicit_profile():
    from services.navigation_behavior import reply_valid

    assert reply_valid({}, {"action": "go", "state": "clear"})
    assert reply_valid({}, {"action": "go", "state": "clear", "behavior": DEFAULT_BEHAVIOR})
