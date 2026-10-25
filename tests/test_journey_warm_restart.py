"""New journey identities reuse a healthy producer, never previous GO or ARM."""

import json
import time

import pytest
from test_journey_runner import runner
from test_navigation_journey import journey as journey
from test_navigation_runner import isolated as isolated
from test_navigation_trial import world as world

from apps.compute import stream_prepare
from services import navigation_config
from services.navigation_trial import TrialError

SOURCE = {"camera_session": "capture", "transport_epoch": 1, "pipeline_revision": 2}


def test_terminal_journey_remains_observe_then_new_intent_gets_new_run_and_lease(isolated):
    instance, safety = runner(isolated)
    old_run, old_lease = instance.run_id, instance.lease
    instance.last_source = SOURCE
    instance.fresh_frame_seen = True
    safety.update(state="DISARMED", can_move=False, owner=None, generation="stopped")
    safety["journey"].update(active=False, reason="operator_stop")
    assert instance._authority() is False
    observe_run = instance.run_id
    assert instance.policy["mode"] == "observe"
    assert instance.lease.deadline is None
    assert old_lease.journey.active is False
    assert not instance.closed.is_set()
    assert instance._authority() is False
    assert instance.run_id == observe_run
    # ARM is insufficient until its matching producer intent is persisted.
    safety.update(state="ARMED", can_move=True, owner="navigation", generation="new")
    safety["journey"].update(id="second-mission", active=True)
    safety["panel_control"]["holder"] = "new-operator-panel"
    safety["operator_control"].update(state="qualifying", operation_id="second-arm")
    assert instance._authority() is False
    isolated[3].update(generation="new", request_id="second-start")
    assert instance._authority() is True
    assert instance.policy["mode"] == "drive"
    assert instance.run_id not in {old_run, observe_run}
    assert instance.lease.deadline is None
    assert instance.lease.feedback_deadline is None
    assert instance.operator_lifecycle.qualification.count == 0
    assert instance.lease.journey.context["id"] == "second-mission"
    assert instance.operator_lifecycle.panel_id == "new-operator-panel"
    assert instance.intent["request_id"] == "second-start"
    old_lease.halt("delayed-old-timeout")
    assert all(row["action"] == "stop" for row in isolated[-1])


def warm_status(world):
    return {
        "warm_navigation_version": 1,
        "warm_ready": True,
        "warm_source": SOURCE,
        "mode": "observe",
        "running": True,
        "config_revision": navigation_config.snapshot()["revision"],
        "sampled_monotonic": world.elapsed,
        "observed_at": time.time(),
        "run_id": "observing",
    }


def prepare_warm(journey, monkeypatch, *, source=SOURCE):
    world, starter, body = journey
    config = navigation_config.snapshot()
    config["mode"] = "drive"
    world.config_path.write_text(json.dumps(config))
    world.active.update(world.manager.registry["s14_venom_navigation"].members)
    world.active.add("rider-venom-navigation.target")
    world.manager._requested["s14_venom_navigation"] = {}
    world.manager._managed_units.update(world.active)
    original = starter.status
    starter.status = lambda: original() or warm_status(world)
    monkeypatch.setattr(stream_prepare, "prepare_stream", lambda **_kw: {"latest_source": source})
    return world, starter, body


def test_fresh_warm_native_source_skips_stop_configure_and_service_restart(journey, monkeypatch):
    world, starter, body = prepare_warm(journey, monkeypatch)
    revision = navigation_config.snapshot()["revision"]
    result = starter.start(body)
    assert result["ok"] is True
    assert result["preparation"]["warm_reused"] is True
    assert result["config"]["revision"] == revision
    assert not any(action == "stop" for _, action in world.actions)
    assert not any("venom-navigation.service" in unit for unit, _ in world.actions)
    assert next(row for row in world.commands if row["action"] == "arm")["journey_id"] == body["request_id"]


def test_changed_source_falls_back_to_cold_preparation(journey, monkeypatch):
    world, starter, body = prepare_warm(journey, monkeypatch, source={**SOURCE, "camera_session": "other"})
    result = starter.start(body)
    assert result["preparation"]["warm_reused"] is False
    assert any("venom-navigation.service" in unit for unit, _ in world.actions)


def test_manual_gesture_during_warm_prepare_invalidates_start_without_stopping_new_owner(journey, monkeypatch):
    world, starter, body = prepare_warm(journey, monkeypatch)
    original = world.submit

    def intervene_after_arm(payload):
        result = original(payload)
        if payload["action"] == "arm":
            world.gate.manual_intervention.transfer(
                {
                    "operator_intervention_version": 1,
                    "intervene": True,
                    "action": "move",
                    "device_settings": True,
                    "source": "manual",
                    "owner": "manual",
                    "arming_mode": "operator",
                    "execution_context": "panel",
                    "operator_consent": True,
                    "operator_plan": "Explicit direction",
                    "panel_id": "operator",
                    "generation": world.gate.generation,
                    "request_id": "takeover",
                    "seq": 10,
                }
            )
        return result

    starter.submit = intervene_after_arm
    with pytest.raises(TrialError, match="navigation_trial_cancelled"):
        starter.start(body)
    assert world.gate.owner == "manual"
    assert world.gate.state == "ARMED"
    assert not any(action == "stop" for _, action in world.actions)


@pytest.mark.parametrize("code", ["navigation_stream_source_mismatch", "navigation_stream_prepare_timeout"])
def test_recoverable_warm_probe_error_takes_cold_path_with_same_guards(journey, monkeypatch, code):
    from apps.compute.client import ComputeError

    world, starter, body = prepare_warm(journey, monkeypatch)
    calls = []

    def prepare(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ComputeError(code, 409)
        return {"latest_source": SOURCE}

    monkeypatch.setattr(stream_prepare, "prepare_stream", prepare)
    result = starter.start(body)
    assert result["ok"] is True
    assert result["preparation"]["warm_reused"] is False
    assert len(calls) == 2
    assert any("venom-navigation.service" in unit for unit, _ in world.actions)


@pytest.mark.parametrize("change", ["deadline", "authority"])
def test_warm_probe_error_never_swallows_preparation_guard(journey, monkeypatch, change):
    from apps.compute.client import ComputeError

    world, starter, body = prepare_warm(journey, monkeypatch)

    def prepare(**_kwargs):
        if change == "deadline":
            from services.navigation_trial import PREPARATION_BUDGET_S

            world.elapsed += PREPARATION_BUDGET_S + 0.01
        else:
            world.gate.disarm("operator_stop")
        raise ComputeError("navigation_stream_prepare_timeout", 504)

    monkeypatch.setattr(stream_prepare, "prepare_stream", prepare)
    expected = "navigation_trial_prepare_timeout" if change == "deadline" else "navigation_trial_cancelled"
    with pytest.raises(TrialError, match=expected):
        starter.start(body)
    assert not any(row["action"] == "arm" for row in world.commands)


def test_host_update_required_during_warm_probe_remains_fatal(journey, monkeypatch):
    from apps.compute.client import ComputeError

    world, starter, body = prepare_warm(journey, monkeypatch)

    def prepare(**_kwargs):
        raise ComputeError("navigation_journey_update_required", 409)

    monkeypatch.setattr(stream_prepare, "prepare_stream", prepare)
    with pytest.raises(TrialError, match="navigation_journey_update_required"):
        starter.start(body)
    assert not any(action == "stop" for _, action in world.actions)
    assert not any(row["action"] == "arm" for row in world.commands)


def test_approval_adoption_finishes_before_warm_reuse_without_stopping_healthy_source(journey, monkeypatch):
    world, starter, body = prepare_warm(journey, monkeypatch)
    revision = navigation_config.snapshot()["revision"]
    original = starter.status

    def adopting():
        row = original()
        if world.elapsed < 0.1 and row.get("mode") == "observe":
            return {**row, "config_revision": revision - 1, "warm_ready": False}
        return row

    starter.status = adopting
    result = starter.start(body)
    assert result["preparation"]["warm_reused"] is True
    assert not any(action == "stop" for _, action in world.actions)
    assert not any("venom-navigation.service" in unit for unit, _ in world.actions)
    assert len([row for row in world.commands if row["action"] == "arm"]) == 1


@pytest.mark.parametrize("supported", [False, True])
def test_warm_reuse_checks_input_region_before_arm(journey, monkeypatch, supported):
    """A warm producer cannot bypass a missing crop capability on the host."""
    from apps.compute.client import ComputeError
    from apps.compute.stream_prepare import _require_input_region

    world, starter, body = prepare_warm(journey, monkeypatch)
    config = navigation_config.snapshot()
    config["perception"]["input_region"] = {"version": 1, "bounds": [0.0, 0.4, 1.0, 1.0]}
    world.config_path.write_text(json.dumps(config))
    calls = []

    def prepare(**kwargs):
        """Simulate host capability validation without acquiring a physical stream."""
        calls.append(kwargs)
        _require_input_region({"input_region_version": 1} if supported else {}, kwargs.get("input_region_version"))
        return {"latest_source": SOURCE}

    monkeypatch.setattr(stream_prepare, "prepare_stream", prepare)
    if supported:
        result = starter.start(body)
        assert result["preparation"]["warm_reused"] is True
    else:
        with pytest.raises(TrialError, match="navigation_input_region_update_required"):
            starter.start(body)
        assert not any(row["action"] == "arm" for row in world.commands)
    assert len(calls) == 1
    assert calls[0]["input_region_version"] == calls[0]["journey_version"] == 1
