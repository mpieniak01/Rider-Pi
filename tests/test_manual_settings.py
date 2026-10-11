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
        {"pulse_duration": 0.5},
        {"linear_rate": 100},
        {"speed_limit": 0.8},
        {"unknown": 1},
    ],
)
def test_invalid_settings_do_not_create_a_config(store, patch):
    with pytest.raises(ValueError):
        store.update(patch, 0)
    assert not store.path().exists()


def test_settings_api_never_publishes_movement(store, monkeypatch):
    app = Flask(__name__)
    app.add_url_rule("/api/calibration/controls", view_func=calibration_api.controls, methods=["GET", "POST"])
    state = {"ready": True, "stale": False, "moving": False, "output": {"lx": 0, "az": 0}}
    monkeypatch.setattr(calibration_api, "read_status", lambda: state)
    monkeypatch.setattr(calibration_api, "_publish", lambda *a: pytest.fail("settings must not publish"))
    client = app.test_client()
    assert client.get("/api/calibration/controls").json["revision"] == 0
    row = client.post("/api/calibration/controls", json={"revision": 0, "values": {"turn_speed": 0.4}})
    assert row.status_code == 200 and row.json["actuation"] is False
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
def test_reversal_never_executes_previous_sign_in_new_pulse(executor, initial, next_direction):
    instance, clock = executor
    arm(instance)
    instance.apply(command(instance, vx=initial, duration=0.25))
    for _ in range(8):
        clock.now += 0.02
        instance.tick(0.02)
    assert instance.controller.o_lx * initial > 0
    instance.adapter.calls = []
    instance.apply(command(instance, vx=next_direction, duration=0.1))
    assert instance.adapter.calls[0] == ("stop",)
    for _ in range(4):
        clock.now += 0.02
        instance.tick(0.02)
    writes = [c[1] for c in instance.adapter.calls if c[0] == "move"]
    assert writes and all(v * next_direction > 0 for v in writes)


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
