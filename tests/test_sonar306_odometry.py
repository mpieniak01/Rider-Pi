"""Odometry ordering characterizations; fictional rates and memory-only transports."""

import copy
from types import SimpleNamespace

import pytest
from flask import Flask
from test_odometry import MOCK_CALIBRATION, accept_stop, estimator as estimator, executor_state, output
from test_odometry_reference import request_row, world as world

from apps.odometry.calibration import calibration_status
from apps.odometry.main import Odometry
from apps.odometry.reference import reference_paths, validate_reference
from services import calibration_api, odometry_api


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"manual_verified": False, "measurement_id": ""}, "manual_calibration_required"),
        ({"measurement_id": "", "conditions": {}}, "measurement_id_required"),
        ({"conditions": {}, "imu_yaw_sign": False}, "measurement_conditions_required"),
        ({"imu_yaw_sign": False, "linear_m_s": {}}, "imu_yaw_direction_unverified"),
        ({"linear_m_s": {}, "turn_rad_s": {"bad": 1}}, "sdk_step_measurements_required"),
        ({"linear_m_s": {"01": 0.2}}, "invalid_sdk_step_measurement"),
    ],
)
def test_calibration_table_validation_precedence(changes, error):
    record = copy.deepcopy(MOCK_CALIBRATION)
    record.update(changes)
    before = copy.deepcopy(record)
    assert calibration_status(record) == error
    assert record == before


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"hardware_ready": False, "sdk_output": {}}, "executor_stationary_unconfirmed"),
        ({"target": {"lx": False, "az": 0}, "sdk_output": {}}, "executor_stationary_unconfirmed"),
        ({"generation": "different", "moving": True}, "executor_sdk_output_mismatch"),
        ({"moving": True}, "executor_stationary_unconfirmed"),
    ],
)
def test_executor_state_shape_and_identity_precede_stationary_confirmation(estimator, changes, error):
    instance, clock = estimator
    accept_stop(instance, clock)
    instance.executor_state = executor_state(instance, clock, **changes)
    assert instance._executor_quality()["error"] == error
    assert instance.reference_id == "fake-origin"
    assert instance.x == instance.y == 0


def test_output_replacement_invalid_sample_precedes_instance_change(estimator):
    instance, clock = estimator
    accept_stop(instance, clock)
    assert not instance.update_output(output(clock, accepted=False, instance_id="replacement"))
    assert instance.reference_id == "fake-origin"
    assert instance.continuity_error == "sdk_output_unconfirmed"
    assert instance.output is None
    assert not instance._idle_confirmed and instance._pending_output_since is None


def test_reference_rejection_is_atomic_for_coordinates_and_continuity(estimator):
    instance, clock = estimator
    accept_stop(instance, clock)
    before = instance.x, instance.y, instance.theta, instance.reference_id, copy.deepcopy(instance.home)
    assert not instance.set_reference(
        reference_id="new", operator_consent=True, x=10, home_operator_confirmed=True, home_x=0
    )
    assert (instance.x, instance.y, instance.theta, instance.reference_id, instance.home) == before
    instance.continuity_error = "old_gap"
    clock.now += 3
    assert not instance.update_imu(float("nan"), observed_at=clock.now)
    assert instance.continuity_error == "old_gap"
    assert instance.quality()["error"] == "old_gap"


@pytest.mark.parametrize(
    "fields,state_fields,error",
    [
        ({"source": "agent"}, {"ready": False}, "reference_requires_fresh_disarmed"),
        ({"source": "agent", "generation": "old"}, {"observed_at": 900}, "safety_stale"),
        ({"source": "agent", "generation": "old"}, {}, "stale_generation"),
        ({"source": "agent", "operator_consent": False}, {}, "reference_metadata_required"),
        ({"ts": 900, "operator_consent": False}, {}, "reference_expired"),
        ({"operator_consent": False, "x": False}, {}, "reference_operator_plan_required"),
        ({"x": False, "home_operator_confirmed": True}, {}, "reference_coordinates_required"),
    ],
)
def test_reference_validation_precedence_never_consumes_journal(world, fields, state_fields, error):
    world.state.update(state_fields)
    row = request_row(world, **fields)
    assert validate_reference(row, world.state, now=world.clock.now) == error
    before = world.estimator.get_pose()
    assert world.control.apply(row)["error"] == error
    assert world.estimator.get_pose() == before
    assert not reference_paths()[1].exists()


def test_reference_replay_precedes_set_reference_and_preserves_journal(world, monkeypatch):
    row = request_row(world)
    assert world.control.apply(row)["accepted"]
    journal = reference_paths()[1].read_bytes()
    monkeypatch.setattr(world.estimator, "set_reference", lambda **_: pytest.fail("replayed reference was applied"))
    assert world.control.apply(row)["error"] == "reference_replayed"
    assert reference_paths()[1].read_bytes() == journal


def test_odometry_loop_subscription_and_cleanup_order():
    events = []

    class Subscriber:
        def __init__(self, name):
            self.name = name

        def recv(self, *, timeout_ms):
            events.append((self.name, timeout_ms))
            return self.name, {}

        def close(self):
            events.append((self.name, "close"))

    runner = Odometry.__new__(Odometry)
    runner.sub_motion = Subscriber("motion.output")
    runner.sub_state = Subscriber("motion.state")
    runner.sub_imu = Subscriber("imu.data")
    runner.sub_reference = Subscriber("odometry.reference")
    runner.pub = SimpleNamespace(close=lambda: events.append(("pub", "close")))

    def fail():
        raise ValueError("fake cycle failure")

    runner._update_and_publish = fail
    with pytest.raises(ValueError, match="fake cycle failure"):
        runner.run()
    assert events == [
        ("motion.output", 10),
        ("motion.state", 0),
        ("imu.data", 10),
        ("odometry.reference", 0),
        ("motion.output", "close"),
        ("motion.state", "close"),
        ("imu.data", "close"),
        ("odometry.reference", "close"),
        ("pub", "close"),
    ]


def test_controls_idle_rejection_prevents_settings_update(monkeypatch):
    from apps.motion import manual_settings

    events = []
    monkeypatch.setattr(calibration_api, "wall_clock", lambda: 1000)
    monkeypatch.setattr(calibration_api, "read_status", lambda: {"observed_at": 1000, "state": "ARMED", "moving": True})
    monkeypatch.setattr(manual_settings, "read", lambda: {"revision": 1})
    monkeypatch.setattr(manual_settings, "_updated", lambda *_: pytest.fail("configuration changed while moving"))
    monkeypatch.setattr(manual_settings, "locked", lambda: __import__('contextlib').nullcontext())
    monkeypatch.setattr(manual_settings, "_atomic", events.append)
    app = Flask(__name__)
    app.add_url_rule('/controls', view_func=calibration_api.controls, methods=['POST'])
    response = app.test_client().post('/controls', json={"revision": 1, "values": {"linear_speed": 0.3}})
    assert response.status_code == 409
    assert response.json["error"] == "manual_settings_requires_idle"
    assert events == []


def test_pending_calibration_rejection_precedes_timeout_and_readiness(monkeypatch):
    now = 1000
    active = {"profile_digest": "a" * 64, "request_id": "older", "activation_state": "applied"}
    pending = {"profile_digest": "b" * 64, "request_id": "new", "generation": "g", "seq": 2, "ts": 900}
    motion = {
        "observed_at": now,
        "calibration": {
            "last_ack": {**pending, "command_generation": "g", "accepted": False, "error": "specific_rejection"}
        },
    }
    monkeypatch.setattr(calibration_api, "wall_clock", lambda: now)
    monkeypatch.setattr(calibration_api, "read_status", lambda: motion)
    monkeypatch.setattr(calibration_api, "odometry_snapshot", lambda: {"observed_at": now})
    monkeypatch.setattr(calibration_api.profiles, "read_active", lambda **_: active)
    monkeypatch.setattr(calibration_api, "_confirmation", lambda *_: "confirmed")
    monkeypatch.setattr(calibration_api, "_pending", pending)
    result = calibration_api.snapshot()
    assert result["status"] == "partial" and result["error"] == "specific_rejection"
    assert result["model_ready"] is False and result["actuation"] is False
    assert pending["ts"] == 900
