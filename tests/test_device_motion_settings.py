"""Targeted settings/profile admission tests; temporary files and fake robot only."""

import json

import pytest
from motion_fakes import command, executor as executor
from test_manual_settings import operator_arm

from apps.motion import manual_settings as settings
from common.motion_commands import normalize_control
from services.safety_contract import command_envelope


def test_direction_only_command_is_resolved_on_pi(executor):
    instance, _ = executor
    row = settings.read()
    row = settings.update(
        {},
        row["revision"],
        directions={
            "forward": {"minimum": 0.1, "speed": 0.25},
            "backward": {"speed": 0.4},
        },
    )
    operator_arm(instance)
    payload = command(instance, device_settings=True, direction="backward", settings_revision=row["revision"])
    for key in ("vx", "yaw", "duration"):
        payload.pop(key)
    normalized = normalize_control(payload)
    assert not {"vx", "yaw", "duration"} & normalized.keys()
    ack = instance.apply(normalized)
    assert ack["status"] == "accepted"
    assert instance.controller.t_lx == -0.4
    assert ack["requested"]["duration"] == row["directions"]["backward"]["duration"]


@pytest.mark.parametrize("mode", ["operator", "timed"])
def test_revision_is_required_in_every_movement_mode(executor, mode):
    instance, _ = executor
    if mode == "operator":
        operator_arm(instance)
    else:
        from motion_fakes import arm

        arm(instance)
    payload = command(instance)
    payload.pop("settings_revision")
    before = list(instance.adapter.calls)
    assert instance.apply(payload)["reason"] == "manual_settings_stale"
    assert instance.adapter.calls == before


def test_nonzero_target_below_minimum_is_rejected_not_boosted(executor):
    instance, _ = executor
    row = settings.read()
    settings.update({}, row["revision"], directions={"forward": {"minimum": 0.15}})
    operator_arm(instance)
    assert instance.apply(command(instance, vx=0.1))["reason"] == "manual_settings_direction_range"
    assert not any(call[0] == "move" for call in instance.adapter.calls)


def test_stop_does_not_read_profile_or_wait_for_its_lock(executor, monkeypatch):
    instance, _ = executor
    operator_arm(instance)
    monkeypatch.setattr(settings, "locked", lambda: pytest.fail("STOP must bypass settings locks"))
    assert instance.apply({"action": "stop"})["status"] == "executed"
    assert instance.gate.state == "DISARMED"


def test_normal_expiry_decelerates_but_keeps_operator_arming(executor):
    instance, clock = executor
    operator_arm(instance)
    instance.apply(command(instance, vx=0.5, duration=0.25))
    outputs = []
    for _ in range(13):
        clock.now += 0.02
        instance.tick(0.02)
        outputs.append(instance.controller.o_lx)
    peak = max(outputs)
    assert peak > 0
    assert any(0 < value < peak for value in outputs[outputs.index(peak) + 1 :])
    assert instance.controller.stopped and instance.gate.state == "ARMED"


def test_corrupt_store_does_not_fall_back_to_defaults(executor):
    instance, _ = executor
    payload = command(
        instance,
        "arm",
        owner="manual",
        operator_consent=True,
        operator_plan="Fake",
        execution_context="panel",
        arming_mode="operator",
    )
    settings.path().write_text('{"revision":')
    ack = instance.apply(payload)
    assert ack["accepted"] is False
    assert instance.controls is None
    assert not instance.snapshot()["ready"]


def test_legacy_effective_speeds_are_migrated_once(executor):
    row = {
        "revision": 7,
        "values": {
            "linear_speed": 1,
            "turn_speed": 1,
            "pulse_duration": 0.25,
            "speed_limit": 0.6,
            "linear_rate": 3,
            "turn_rate": 4,
        },
    }
    settings.path().write_text(json.dumps(row))
    migrated = settings.read()
    assert migrated["schema_version"] == 2 and migrated["revision"] == 8
    assert migrated["directions"]["forward"]["speed"] == 0.6
    assert migrated["directions"]["left"]["speed"] == 0.6
    assert settings.read() == migrated


def test_direction_only_http_envelope_does_not_insert_defaults(executor, monkeypatch):
    instance, clock = executor
    import services.safety_contract as transport

    monkeypatch.setattr(transport.time, "time", clock)
    payload = command(instance, device_settings=True, direction="left")
    for key in ("vx", "yaw", "duration"):
        payload.pop(key)
    envelope = command_envelope(normalize_control(payload))
    assert not {"vx", "yaw", "duration"} & envelope.keys()
    assert envelope["settings_revision"] == settings.read()["revision"]


def test_armed_idle_api_save_preserves_arming_and_next_pulse_uses_new_values(executor, monkeypatch):
    from flask import Flask

    from services import calibration_api

    instance, clock = executor
    operator_arm(instance)
    generation = instance.gate.generation
    monkeypatch.setattr(calibration_api, "wall_clock", clock)
    monkeypatch.setattr(calibration_api, "read_status", instance.snapshot)
    monkeypatch.setattr(calibration_api, "_publish", lambda *a: pytest.fail("configuration must not publish movement"))
    app = Flask(__name__)
    app.add_url_rule("/controls", view_func=calibration_api.controls, methods=["POST"])
    client = app.test_client()
    revision = settings.read()["revision"]
    response = client.post(
        "/controls", json={"revision": revision, "values": {}, "directions": {"forward": {"speed": 0.3}}}
    )
    assert response.status_code == 200
    assert instance.gate.state == "ARMED" and instance.gate.generation == generation
    payload = command(instance, device_settings=True, direction="forward", settings_revision=response.json["revision"])
    for key in ("vx", "yaw", "duration"):
        payload.pop(key)
    assert instance.apply(payload)["status"] == "accepted"
    assert instance.controller.t_lx == 0.3
    response = client.post(
        "/controls",
        json={"revision": response.json["revision"], "values": {}, "directions": {"forward": {"speed": 0.4}}},
    )
    assert response.status_code == 409
    assert settings.read()["directions"]["forward"]["speed"] == 0.3
    assert instance.gate.state == "ARMED"


def test_schema_two_missing_directions_is_not_reconstructed(executor):
    row = settings.read()
    row.pop("directions")
    settings.path().write_text(json.dumps(row))
    with pytest.raises(ValueError):
        settings.read()


def test_minimum_must_be_reachable_within_impulse(executor):
    row = settings.read()
    with pytest.raises(ValueError):
        settings.update({}, row["revision"], directions={"forward": {"minimum": 0.5, "speed": 0.5}})
    assert settings.read() == row


def test_newest_same_sign_intent_cancels_superseded_reversal(executor):
    instance, clock = executor
    operator_arm(instance)
    instance.apply(command(instance, vx=0.4, duration=0.25))
    for _ in range(3):
        clock.now += 0.02
        instance.tick(0.02)
    instance.apply(command(instance, vx=-0.4, duration=0.25))
    assert instance.controller.reversing
    before = instance.controller.o_lx
    instance.apply(command(instance, vx=0.4, duration=0.25))
    assert not instance.controller.reversing
    clock.now += 0.02
    instance.tick(0.02)
    assert instance.controller.o_lx >= before
    instance.apply(command(instance, vx=-0.4, duration=0.25))
    instance.apply(command(instance, vx=0, duration=0.25))
    assert not instance.controller.reversing
    assert instance.controller.reverse_until is None


def test_profile_change_racing_published_idle_does_not_change_active_ramp(executor):
    instance, clock = executor
    operator_arm(instance)
    instance.apply(command(instance, vx=0.4, duration=0.25))
    previous_limits = instance.controller.limits
    row = settings.read()
    newer = settings.update({"linear_rate": 2}, row["revision"])
    ack = instance.apply(command(instance, vx=0.3, settings_revision=newer["revision"]))
    assert ack["reason"] == "manual_settings_requires_idle"
    assert instance.controller.limits == previous_limits
    for _ in range(14):
        clock.now += 0.02
        instance.tick(0.02)
    instance.refresh_controls(force=True)
    assert instance.controller.limits.linear_rate == 2
    assert instance.gate.state == "ARMED"
