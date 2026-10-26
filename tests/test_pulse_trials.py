"""Pulse recipes use fake time, private settings and an in-memory adapter only."""

import json

import pytest
from flask import Flask
from motion_fakes import command, executor as executor
from test_held_motion import advance, intent

from apps.motion import manual_settings as settings
from apps.motion.trial_profiles import PROFILES
from services.api_core import pulse_trials_api as api


def start(instance, profile="A", **changes):
    row = settings.read()
    row = settings.update(
        {}, row["revision"], directions={"forward": {"duration": PROFILES[profile]["pulse_ms"] / 1000}}
    )
    payload = command(
        instance,
        "arm",
        request_id="trial-" + profile,
        owner="manual",
        arming_mode="operator",
        execution_context="panel",
        panel_id="trial-panel",
        operator_consent=True,
        operator_plan="Mock-only pulse trial",
        trial_profile_id=profile,
        trial_version=1,
        settings_revision=row["revision"],
    )
    for key in ("vx", "yaw", "duration"):
        payload.pop(key)
    payload.update(changes)
    return payload, instance.apply(payload)


@pytest.mark.parametrize("profile", ["A", "B", "C"])
def test_recipes_finish_with_zero_disarm_and_real_gaps(executor, profile):
    instance, clock = executor
    payload, ack = start(instance, profile)
    assert ack["status"] == "executed"
    assert instance.trials.active
    advance(instance, clock, 1.4)
    run = instance.trials.snapshot()["current"]
    assert run["phase"] == "completed"
    assert run["completed_pulses"] == PROFILES[profile]["count"]
    starts = [e for e in run["events"] if e["kind"] == "pulse_started"]
    zeros = [e for e in run["events"] if e["kind"] == "pulse_zero"]
    assert len(starts) == len(zeros) == PROFILES[profile]["count"]
    for zero, following in zip(zeros, starts[1:]):
        assert following["elapsed_ms"] - zero["elapsed_ms"] >= 100 - 1e-6
    assert instance.controller.stopped
    assert instance.gate.state == "DISARMED"
    assert instance.gate.generation != payload["generation"]
    assert len(json.dumps(instance.snapshot()).encode()) < 65536


@pytest.mark.parametrize("at", [0.04, 0.14, 0.32, 0.82])
def test_stop_cancels_every_phase_without_late_restart(executor, at):
    instance, clock = executor
    start(instance, "C")
    advance(instance, clock, at)
    instance.process_batch([("motion.command", {"action": "stop", "request_id": "stop-now"})])
    after = len(instance.adapter.calls)
    advance(instance, clock, 1.8)
    assert instance.trials.current["phase"] == "cancelled"
    assert instance.gate.state == "DISARMED"
    assert not any(c[0] == "move" and (c[1] or c[2]) for c in instance.adapter.calls[after:])


def test_duplicate_is_read_only_and_changed_replay_conflicts(executor):
    instance, clock = executor
    payload, _ = start(instance)
    advance(instance, clock, 0.8)
    after = len(instance.adapter.calls)
    assert instance.apply(payload)["reason"] == "pulse_trial_replay"
    assert len(instance.adapter.calls) == after
    assert instance.apply({**payload, "ts": payload["ts"] + 1})["reason"] == "pulse_trial_request_conflict"
    assert len(instance.adapter.calls) == after


def test_manual_intervention_supersedes_series_without_disarming_new_goal(executor):
    instance, clock = executor
    start(instance, "C")
    advance(instance, clock, 0.14)
    payload = intent(instance, "hold", direction="backward", panel_id="trial-panel", request_id="new-manual")
    assert instance.apply(payload)["status"] == "accepted"
    advance(instance, clock, 0.2)
    assert instance.trials.current["phase"] == "cancelled"
    assert instance.gate.state == "ARMED"
    assert instance.controller.t_lx < 0
    assert instance.controller.o_lx < 0


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"operator_consent": False}, "operator_consent_required"),
        ({"generation": "old"}, "stale_generation"),
        ({"seq": -1}, "stale_sequence"),
        ({"settings_revision": -1}, "manual_settings_stale"),
        ({"trial_version": True}, "pulse_trial_version_invalid"),
        ({"trial_context": "x" * 81}, "pulse_trial_context_invalid"),
        ({"panel_id": ""}, "invalid_panel_id"),
        ({"duration": 0.5}, "pulse_trial_ambiguous"),
    ],
)
def test_rejections_do_not_arm_or_drive(executor, changes, reason):
    instance, _ = executor
    before = list(instance.adapter.calls)
    _, result = start(instance, **changes)
    assert result["status"] == "rejected"
    assert result["reason"] == reason
    assert instance.gate.state == "DISARMED"
    assert instance.adapter.calls == before


def test_series_deadline_ends_without_renewal(executor):
    instance, clock = executor
    start(instance, "C")
    clock.now += 1.6
    instance.tick(0.02)
    assert instance.trials.current["phase"] in {"cancelled", "failed"}
    assert instance.gate.state == "DISARMED"
    assert instance.controller.stopped


def test_first_request_expired_does_not_arm(executor):
    instance, clock = executor
    _, ack = start(instance, ts=clock.now - 1)
    assert ack["reason"] == "expired_command"
    assert instance.gate.state == "DISARMED"


def test_start_requires_profile_duration_and_keeps_named_profiles(executor):
    instance, clock = executor
    row = settings.read()
    payload, _ = start(instance, "B")
    payload.update(request_id="not-matching", trial_profile_id="A")
    assert instance.apply({"action": "stop"})["status"] == "executed"
    payload.update(generation=instance.gate.generation, seq=0, ts=clock.now)
    assert instance.apply(payload)["reason"] == "pulse_trial_settings_mismatch"
    assert settings.read()["profiles"] == row["profiles"]


def test_catalog_and_status_cannot_dispatch(monkeypatch):
    app = Flask(__name__)
    app.add_url_rule('/profiles', view_func=api.catalog)
    app.add_url_rule('/trial/<request_id>', view_func=api.status)
    monkeypatch.setattr(api, 'read_status', lambda: {'stale': False, 'pulse_trials': {'version': 1, 'current': None}})
    monkeypatch.setattr(api, 'submit_control', lambda *_: pytest.fail('GET must not actuate'))
    client = app.test_client()
    assert len(client.get('/profiles').json['profiles']) == 3
    assert client.get('/profiles').json['supported'] is True
    assert client.get('/trial/missing').status_code == 404


def test_failed_zero_stops_remaining_pulses(executor):
    instance, clock = executor
    start(instance, "C")
    instance.adapter.stop = lambda: False
    advance(instance, clock, 0.4)
    assert instance.trials.current["phase"] in {"failed", "cancelled"}
    assert instance.trials.current["completed_pulses"] == 0
    assert instance.gate.state == "DISARMED"


def test_changed_settings_at_gap_cannot_replan_series(executor):
    instance, clock = executor
    start(instance, "C")
    advance(instance, clock, 0.14)
    instance.controls["revision"] += 10
    instance.tick(0.02)
    assert not instance.trials.active
    assert instance.gate.state == "DISARMED"


def test_group_identity_ignores_test_duration_but_keeps_common_ramps(executor):
    instance, clock = executor
    start(instance, "A")
    advance(instance, clock, 0.8)
    group = instance.trials.current["group_id"]
    start(instance, "B")
    advance(instance, clock, 0.8)
    assert instance.trials.current["group_id"] == group
    row = settings.read()
    settings.update({"linear_rate": 0.8}, row["revision"])
    start(instance, "C")
    assert instance.trials.current["group_id"] != group


def test_sensor_loss_cannot_become_a_completed_pulse_and_resume(executor):
    instance, clock = executor
    start(instance, "C")
    instance.samples.quality = lambda: {"ready": False, "error": "sensor_unavailable"}
    clock.now += 0.02
    instance.tick(0.02)
    assert instance.trials.current["phase"] in {"failed", "cancelled"}
    assert not instance.trials.active
    assert instance.gate.state == "DISARMED"


def test_manual_cancellation_boundary_during_gap_ends_the_whole_series(executor):
    instance, clock = executor
    start(instance, "C")
    advance(instance, clock, 0.14)
    instance.gate.cancel_motion("invalid_motion_intent")
    instance.controller.stop()
    instance.tick(0.02)
    assert not instance.trials.active
    assert instance.gate.state == "DISARMED"


@pytest.mark.parametrize(
    "extra", [{"mode": "hold"}, {"device_settings": True}, {"height": 5}, {"direction": "backward"}]
)
def test_trial_never_accepts_a_second_actuator_instruction(executor, extra):
    instance, _ = executor
    _, ack = start(instance, **extra)
    assert ack["reason"] == "pulse_trial_ambiguous"
    assert instance.gate.state == "DISARMED"


def test_absolute_series_deadline_precedes_nonzero_adapter_write(executor):
    instance, clock = executor
    start(instance, "B")
    clock.now += 1.2
    instance.poll_sensors()
    instance.tick(0.02)
    clock.now += 0.12
    instance.poll_sensors()
    instance.tick(0.02)
    assert instance.trials.current["phase"] == "pulse"
    before = len(instance.adapter.calls)
    clock.now += 0.2
    instance.poll_sensors()
    instance.tick(0.02)
    assert instance.trials.current["reason"] == "pulse_trial_deadline"
    assert not any(call[0] == "move" and (call[1] or call[2]) for call in instance.adapter.calls[before:])
