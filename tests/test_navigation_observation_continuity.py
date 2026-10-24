"""First-start and terminal observation regressions; executor is entirely inert."""

import json

import pytest
from navigation_runner_fixtures import isolated as isolated
from test_navigation_trial import world as world

from apps.compute import navigation
from services import navigation_config


def acceptance(policy):
    return {
        **policy,
        "verified": True,
        "calibration_id": "operator-acceptance",
        "model_sha256": "a" * 64,
        "avoidance": {**policy["avoidance"], "sweep_verified": True},
    }


def test_acceptance_only_preserves_requested_observer(world):
    old = navigation_config.snapshot()
    world.manager._state_path.write_text(json.dumps({"requested": ["s15_venom_perception"]}))
    proposed = acceptance(old)
    values = {k: v for k, v in proposed.items() if k not in {"protocol_version", "revision"}}
    saved = navigation_config.configure({"revision": old["revision"], "values": values})
    assert saved["revision"] == old["revision"] + 1
    assert saved["verified"] is True
    assert saved["avoidance"]["sweep_verified"] is True
    assert json.loads(world.manager._state_path.read_text())["requested"] == ["s15_venom_perception"]
    assert world.commands == world.actions == []


@pytest.mark.parametrize(
    "field,value", [("speed", 0.11), ("corridor", [0.3, 0.8, 0.7, 0.95]), ("decision_budget_ms", 400)]
)
def test_acceptance_cannot_smuggle_parameter_changes_into_running_observation(world, field, value):
    old = navigation_config.snapshot()
    world.manager._state_path.write_text(json.dumps({"requested": ["s15_venom_perception"]}))
    proposed = {**acceptance(old), field: value}
    values = {k: v for k, v in proposed.items() if k not in {"protocol_version", "revision"}}
    with pytest.raises(ValueError, match="stop_goals_first"):
        navigation_config.configure({"revision": old["revision"], "values": values})
    assert navigation_config.snapshot() == old


def test_observer_adopts_only_approval_revision_without_closing_source(isolated):
    policy, _, _, _, commands = isolated
    instance = navigation.NavigationRunner(observe_only=True)
    original_run = instance.run_id
    instance.last_result = {"state": "clear", "clear_count": 9}
    instance.fresh_frame_seen = True
    policy.update(acceptance(policy), revision=policy["revision"] + 1)
    instance._start_cycle()
    assert not instance.closed.is_set()
    assert instance.saved_policy == policy
    assert instance.policy["mode"] == "observe"
    assert instance.run_id != original_run
    assert instance.last_result is None
    assert instance.lease.deadline is None
    assert commands == []


def test_active_driver_rejects_even_approval_revision(isolated):
    policy = isolated[0]
    instance = navigation.NavigationRunner()
    policy.update(acceptance(policy), revision=policy["revision"] + 1)
    with pytest.raises(navigation.ComputeError, match="navigation_configuration_changed"):
        instance._start_cycle()


@pytest.mark.parametrize("new_state,owner", [("DISARMED", None), ("ARMED", "manual"), ("ESTOP", None)])
def test_superseded_scoped_stop_keeps_passive_source_available(isolated, monkeypatch, new_state, owner):
    safety, commands = isolated[2], isolated[-1]
    safety.update(ready=True, stale=False, state="ARMED")
    instance = navigation.NavigationRunner()
    instance._authority()
    generation = instance.generation

    def superseded(payload):
        commands.append(payload)
        safety.update(state=new_state, owner=owner, can_move=new_state == "ARMED", generation="new-authority")
        return {"ok": False, "error": "stale_stop_generation"}, 409

    monkeypatch.setattr(navigation, "submit_control", superseded)
    instance.stop()
    assert not instance.closed.is_set()
    assert len(commands) == 1
    assert commands[0]["action"] == "stop"
    assert commands[0]["expected_generation"] == generation
    assert safety["generation"] == "new-authority"


@pytest.mark.parametrize(
    "change,error",
    [
        ({"generation": "gen"}, "stale_stop_generation"),
        ({"generation": "new", "stale": True}, "stale_stop_generation"),
        ({"generation": "new", "ready": False}, "stale_stop_generation"),
        ({"generation": "new"}, "executor_unavailable"),
    ],
)
def test_unconfirmed_stop_still_terminates_runner(isolated, monkeypatch, change, error):
    safety = isolated[2]
    safety.update(ready=True, stale=False, state="ARMED")
    instance = navigation.NavigationRunner()
    instance._authority()

    def rejected(_payload):
        safety.update(change)
        return {"ok": False, "error": error}, 409

    monkeypatch.setattr(navigation, "submit_control", rejected)
    instance.stop()
    assert instance.closed.is_set()


@pytest.mark.parametrize("passive", [True, False])
def test_s14_approval_requires_a_confirmed_passive_observer(world, monkeypatch, passive):
    from services import navigation_approval

    old = navigation_config.snapshot()
    world.manager._state_path.write_text(json.dumps({"requested": ["s14_venom_navigation"]}))
    monkeypatch.setattr(
        navigation_approval, "passive_navigation_matches", lambda revision: passive and revision == old["revision"]
    )
    proposed = acceptance(old)
    values = {k: v for k, v in proposed.items() if k not in {"protocol_version", "revision"}}
    if passive:
        saved = navigation_config.configure({"revision": old["revision"], "values": values})
        assert saved["verified"] is True
    else:
        with pytest.raises(ValueError, match="navigation_stop_goals_first"):
            navigation_config.configure({"revision": old["revision"], "values": values})
    assert world.commands == world.actions == []


def test_timeout_revokes_motion_but_does_not_close_the_passive_runner_on_stop_race(isolated, monkeypatch):
    from test_journey_runner import runner

    instance, safety = runner(isolated)
    safety.update(ready=True, stale=False)
    old_run = instance.run_id
    commands = isolated[-1]

    def superseded(payload):
        commands.append(payload)
        safety.update(state="DISARMED", owner=None, can_move=False, generation="already-revoked")
        safety["journey"].update(active=False, state="failed", reason="decision_timeout")
        return {"ok": False, "error": "stale_stop_generation"}, 409

    monkeypatch.setattr(navigation, "submit_control", superseded)
    old_lease = instance.lease
    old_lease.halt("decision_timeout")
    assert instance._authority() is False
    assert instance.policy["mode"] == "observe"
    assert instance.run_id != old_run
    assert not instance.closed.is_set()
    assert instance.lease.deadline is None
    assert instance.operator_lifecycle.last_journey["reason"] == "decision_timeout"
    assert all(command["action"] == "stop" for command in commands)


@pytest.mark.parametrize("value", [None, [], "invalid", 1])
def test_malformed_approval_does_not_bypass_validation_or_crash(world, value):
    from services.navigation_approval import approval_only

    old = navigation_config.snapshot()
    proposed = {**acceptance(old), "revision": old["revision"] + 1, "avoidance": value}
    assert approval_only(old, proposed) is False


@pytest.mark.parametrize(
    "change,safety_change,expected",
    [
        ({}, {}, True),
        ({"running": False}, {}, False),
        ({"mode": "drive"}, {}, False),
        ({"config_revision": 99}, {}, False),
        ({"sampled_monotonic": float("nan")}, {}, False),
        ({"sampled_monotonic": 0}, {}, False),
        ({}, {"stale": True}, False),
        ({}, {"can_move": True, "owner": "navigation"}, False),
        ({}, {"journey": {"active": True}}, False),
    ],
)
def test_passive_s14_approval_requires_current_revision_and_revoked_authority(
    world, monkeypatch, change, safety_change, expected
):
    import time

    from services import navigation_approval, navigation_trial, safety_contract

    status = {"running": True, "mode": "observe", "config_revision": 4, "sampled_monotonic": time.monotonic(), **change}
    safety = {
        "ready": True,
        "stale": False,
        "state": "DISARMED",
        "can_move": False,
        "owner": None,
        "journey": {"active": False},
        **safety_change,
    }
    monkeypatch.setattr(navigation_trial, "navigation_status", lambda: status)
    monkeypatch.setattr(safety_contract, "read_status", lambda: safety)
    assert navigation_approval.passive_navigation_matches(4) is expected
