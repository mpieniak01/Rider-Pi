"""Private files and fake adapters only; no hardware or network."""

import pytest
from flask import Flask
from motion_fakes import arm, command, executor as executor

from apps.motion import manual_settings as settings
from services import calibration_api


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_MANUAL_SETTINGS_PATH", str(tmp_path / "controls.json"))
    for key in ["MOTION_RAMP_LX", "MOTION_RAMP_AZ", "MOTION_SPEED_LIMIT"]:
        monkeypatch.delenv(key, raising=False)
    return settings


def test_one_persistent_revision_and_stale_writer_conflict(store):
    before = store.read()
    assert before["values"]["pulse_duration"] == 0.25
    one = store.update({"linear_speed": 0.3, "turn_speed": 0.4}, before["revision"])
    assert store.read() == one
    with pytest.raises(ValueError, match="conflict"):
        store.update({"linear_speed": 0.9}, before["revision"])
    assert store.read() == one
    assert store.path().stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "patch",
    [
        {"linear_speed": True},
        {"turn_speed": float("nan")},
        {"pulse_duration": 1.01},
        {"linear_rate": 101},
        {"speed_limit": 0.8},
        {"unknown": 1},
    ],
)
def test_invalid_settings_do_not_create_a_config(store, patch):
    before = store.read()
    with pytest.raises(ValueError):
        store.update(patch, 0)
    assert store.read() == before


def test_settings_api_never_publishes_movement(store, monkeypatch):
    app = Flask(__name__)
    app.add_url_rule("/api/calibration/controls", view_func=calibration_api.controls, methods=["GET", "POST"])
    state = {
        "ready": True,
        "state": "DISARMED",
        "observed_at": calibration_api.wall_clock(),
        "stale": False,
        "moving": False,
        "output": {"lx": 0, "az": 0},
        "target": {"lx": 0, "az": 0},
    }
    monkeypatch.setattr(calibration_api, "read_status", lambda: state)
    monkeypatch.setattr(calibration_api, "_publish", lambda *a: pytest.fail("settings must not publish"))
    client = app.test_client()
    assert client.get("/api/calibration/controls").json["revision"] == 0
    row = client.post("/api/calibration/controls", json={"revision": 0, "values": {"turn_speed": 0.4}})
    assert row.status_code == 200
    assert row.json["actuation"] is False
    assert (
        client.post("/api/calibration/controls", json={"revision": 0, "values": {"turn_speed": 0.5}}).status_code == 409
    )
    state["moving"] = True
    assert (
        client.post("/api/calibration/controls", json={"revision": 1, "values": {"turn_speed": 0.5}}).status_code == 409
    )
    assert store.read()["values"]["turn_speed"] == 0.4


def operator_arm(instance):
    return instance.apply(
        command(
            instance,
            "arm",
            owner="manual",
            operator_consent=True,
            operator_plan="Mock-only controls",
            execution_context="panel",
            arming_mode="operator",
        )
    )


def test_old_panel_revision_and_old_values_are_rejected(executor):
    instance, _ = executor
    operator_arm(instance)
    row = settings.read()
    payload = command(
        instance, direction="forward", **settings.pulse(row, "forward"), settings_revision=row["revision"]
    )
    newer = settings.update({"linear_speed": 0.3}, row["revision"])
    assert instance.apply(payload)["reason"] == "manual_settings_stale"
    payload["settings_revision"] = newer["revision"]
    assert instance.apply(payload)["reason"] == "manual_settings_mismatch"
    assert not any(c[0] == "move" for c in instance.adapter.calls)
    payload.update(settings.pulse(newer, "forward"))
    assert instance.apply(payload)["status"] == "accepted"


@pytest.mark.parametrize("initial,next_direction", [(0.6, -0.6), (-0.6, 0.6)])
def test_reversal_brakes_through_zero_within_original_deadline(executor, initial, next_direction):
    instance, clock = executor
    operator_arm(instance)
    instance.apply(command(instance, vx=initial, duration=0.25))
    for _ in range(6):
        clock.now += 0.02
        instance.tick(0.02)
    previous = instance.controller.o_lx
    assert previous * initial > 0
    instance.adapter.calls = []
    instance.apply(command(instance, vx=next_direction, duration=0.25))
    deadline = instance.controller.deadline
    outputs = []
    for _ in range(13):
        clock.now += 0.02
        instance.tick(0.02)
        outputs.append(instance.controller.o_lx)
        if instance.controller.deadline:
            assert instance.controller.deadline == deadline
    opposite = next(i for i, value in enumerate(outputs) if value * next_direction > 0)
    assert any(value == 0 for value in outputs[:opposite])
    assert all(abs(value) <= abs(previous) for value in outputs[:opposite])
    assert instance.controller.stopped
    assert instance.gate.state == "ARMED"


def test_shared_defaults_reach_requested_speed_within_default_pulse(executor):
    instance, clock = executor
    operator_arm(instance)
    row = settings.read()
    for direction in ["forward", "backward", "left", "right"]:
        instance.controller.stop()
        payload = command(
            instance, direction=direction, settings_revision=row["revision"], **settings.pulse(row, direction)
        )
        assert instance.apply(payload)["status"] == "accepted"
        for _ in range(5):
            clock.now += 0.02
            instance.tick(0.02)
        assert (
            abs(instance.controller.o_lx) == row["values"]["linear_speed"]
            if direction in ["forward", "backward"]
            else abs(instance.controller.o_az) == row["values"]["turn_speed"]
        )
        instance.poll_sensors()


def test_full_manual_range_and_half_second_pulse_are_persisted(store):
    before = store.read()
    row = store.update(
        {"linear_rate": 8, "linear_deceleration": 8},
        before["revision"],
        directions={"forward": {"maximum": 1, "speed": 1, "duration": 0.5}},
    )
    assert row["directions"]["forward"]["speed"] == 1
    assert row["directions"]["forward"]["duration"] == 0.5
    assert row["values"]["speed_limit"] == 1
    assert store.read() == row


def test_legacy_sixty_percent_cap_is_derived_from_new_direction_maximum(store):
    row = store.read()
    # Reproduce the deployed legacy settings without touching any hardware.
    for item in row["directions"].values():
        item["maximum"] = 0.6
    row["values"]["speed_limit"] = 0.6
    store._atomic(row)
    changed = store.update({}, row["revision"], directions={"backward": {"maximum": 1}})
    assert changed["values"]["speed_limit"] == 1
    assert changed["directions"]["backward"]["speed"] == row["directions"]["backward"]["speed"]
    assert changed["directions"]["forward"] == row["directions"]["forward"]


def test_half_second_panel_pulse_is_not_clipped_by_command_freshness(executor):
    instance, clock = executor
    operator_arm(instance)
    row = settings.read()
    row = settings.update({}, row["revision"], directions={"forward": {"duration": 0.5}})
    request = command(
        instance,
        direction="forward",
        device_settings=True,
        execution_context="panel",
        settings_revision=row["revision"],
    )
    started = clock.now
    ack = instance.apply(request)
    assert ack["status"] == "accepted", ack
    assert instance.controller.deadline == started + 0.5
    for _ in range(15):
        clock.now += 0.02
        instance.poll_sensors()
        instance.tick(0.02)
    assert not instance.controller.stopped  # Still running after 300 ms.
    assert instance.apply(command(instance, "stop"))["status"] == "executed"
    assert instance.controller.stopped


def test_half_second_pulse_does_not_allow_old_or_raw_commands(executor):
    instance, clock = executor
    operator_arm(instance)
    row = settings.read()
    row = settings.update({}, row["revision"], directions={"forward": {"duration": 0.5}})
    stale = command(instance, direction="forward", device_settings=True, settings_revision=row["revision"])
    clock.now += 0.6
    assert instance.apply(stale)["status"] == "rejected"
    assert not any(c[0] == "move" for c in instance.adapter.calls)
    raw = command(instance, vx=0.2, duration=1, settings_revision=row["revision"])
    assert instance.apply(raw)["status"] == "rejected"
