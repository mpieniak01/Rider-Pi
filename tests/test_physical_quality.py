"""Motion/quality arithmetic with in-memory adapters. Never opens SDK or BUS."""

from types import SimpleNamespace

import pytest
from motion_fakes import arm, command, executor as executor
from quality_fakes import fake_home

from apps.motion.dynamics import RampLimits, approach
from apps.motion.sensor_quality import SensorSamples
from apps.motion.sensor_reader import project_sensor_payload
from common.data_quality import pose_status, sample_status


@pytest.mark.parametrize("start,target", [(0.03, -1), (-0.03, 1)])
def test_reversal_reaches_zero_before_changing_sign(start, target):
    zero = approach(start, target, 2.0, 0.1)
    assert zero == 0
    assert approach(zero, target, 2.0, 0.1) == pytest.approx(0.2 if target > 0 else -0.2)


@pytest.mark.parametrize("dt", [0, -0.1, 0.11, float("nan"), float("inf"), True])
def test_invalid_dt_stops_disarms_and_cancels_pending(executor, dt):
    instance, _ = executor
    arm(instance)
    instance.apply(command(instance))
    instance.tick(dt)
    assert instance.gate.state == "DISARMED"
    assert instance.controller.stopped
    assert instance.last_ack["status"] == "rejected"
    assert instance.adapter.calls[-1] == ("stop",)


def test_tiny_nonzero_output_is_not_reported_stationary(executor):
    instance, _ = executor
    arm(instance)
    instance.apply(command(instance, vx=0.0005))
    instance.tick(0.02)
    assert not instance.controller.stopped
    assert instance.snapshot()["moving"] is True


def test_zero_pause_is_immediate_and_acknowledged_without_revoking_lease(executor):
    instance, clock = executor
    arm(instance)
    instance.apply(command(instance, vx=0.3))
    instance.tick(0.02)
    generation = instance.gate.generation
    clock.now += 0.01
    ack = instance.apply(command(instance, vx=0, yaw=0))
    assert ack["status"] == "executed"
    assert ack["reason"] == "sdk_zero_accepted"
    assert instance.adapter.calls[-1] == ("move", 0, 0)
    assert instance.gate.state == "ARMED"
    assert instance.gate.generation == generation
    clock.now += 0.3
    instance.tick(0.02)
    assert instance.gate.state == "DISARMED"
    assert instance.gate.generation != generation


@pytest.mark.parametrize(
    "field,value",
    [("linear_rate", 0), ("turn_rate", float("nan")), ("speed_limit", 1.1), ("max_dt_s", 1), ("watchdog_s", 1)],
)
def test_invalid_ramp_configuration_denies_arm(executor, field, value):
    instance, _ = executor
    instance.controller.limits = RampLimits(**{field: value})
    assert arm(instance)["status"] == "rejected"
    assert not instance.snapshot()["ready"]


@pytest.mark.parametrize("name", ["roll", "pitch", "yaw", "battery"])
def test_missing_sensor_disarms_through_same_gate(executor, name):
    instance, _ = executor
    arm(instance)
    instance.apply(command(instance))
    instance.tick(0.02)
    instance.samples.observe(name, None)
    instance.tick(0.02)
    assert instance.gate.state == "DISARMED"
    assert not instance.snapshot()["can_move"]
    assert instance.controller.stopped


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), True, -0.1, 1.1])
def test_battery_unknown_or_out_of_range_is_not_zero(value):
    samples = SensorSamples(lambda: 100, lambda: 100)
    samples.observe("battery", value)
    row = samples.quality()["sensors"]["battery"]
    assert row["value"] is None
    assert not row["ready"]


def test_source_time_and_monotonic_time_are_independently_checked():
    clock = SimpleNamespace(mono=100, wall=100)
    samples = SensorSamples(lambda: clock.mono, lambda: clock.wall)
    for key in ("roll", "pitch", "yaw", "battery"):
        samples.observe(key, 0.5)
    assert samples.quality()["ready"]
    samples.observe("yaw", 1, measured_at=99.9)
    assert not samples.quality()["sensors"]["yaw"]["ready"]
    samples.observe("yaw", 1, monotonic_at=101)
    assert not samples.quality()["sensors"]["yaw"]["ready"]
    samples.observe("yaw", 1, measured_at=100.05)
    assert not samples.quality()["sensors"]["yaw"]["ready"]
    clock.wall = 1000
    assert not samples.quality()["ready"]


def test_projection_never_rejuvenates_stale_missing_source_time():
    row = {"ts": 100, "imu": {"roll": 0, "pitch": 0, "yaw": 0}, "battery": 0}
    imu, device = project_sensor_payload(row, now=100)
    assert not imu["imu_ok"]
    assert device["battery_pct"] is None
    row["sensor_observed_at"] = {key: 99 for key in ("roll", "pitch", "yaw", "battery")}
    imu, device = project_sensor_payload(row, now=100)
    assert imu["observed_at"] == 99
    assert device["battery_pct"] == 0
    row["ts"] = 200
    imu, device = project_sensor_payload(row, now=200)
    assert not imu["imu_ok"]
    assert device["battery_pct"] is None


@pytest.mark.parametrize(
    "row",
    [
        {},
        {"observed_at": None, "ts": 100},
        {"observed_at": 101},
        {"observed_at": 99},
        {"observed_at": 100, "error": "offline"},
        {"observed_at": 100, "data_ready": False},
    ],
)
def test_generic_source_quality_is_fail_closed(row):
    assert not sample_status(row, max_age_s=0.5, now=100)["ready"]


def test_pose_calibration_and_order_are_required():
    row = {"x": 0, "y": 0, "theta": 0, "observed_at": 100}
    assert not pose_status(row, now=100)["ready"]
    row.update(navigation_ready=True, calibration_id="fictional", reference_id="mock-origin", confidence=0.8)
    row["home"] = fake_home("fictional", "mock-origin")
    assert pose_status(row, now=100)["ready"]
    assert not pose_status(row, now=100, previous_ts=100.01)["ready"]


def test_sdk_output_ledger_only_reports_actual_write_time(executor):
    instance, clock = executor
    sent = []
    instance.publisher = SimpleNamespace(publish=lambda topic, row, **kw: sent.append((topic, row)))
    instance.adapter.output_status = lambda: {"linear_step": 1, "turn_step": 0}
    arm(instance)
    instance.apply(command(instance))
    instance.tick(0.02)
    output = instance.sdk_output()
    clock.now += 0.1
    assert instance.sdk_output()["observed_at"] == output["observed_at"]
    assert output["linear_step"] == 1
    assert output["physical_completion"] == "unverified"


def test_replacement_goal_after_deadline_cannot_hide_timeout(executor):
    instance, clock = executor
    arm(instance)
    instance.apply(command(instance, duration=0.1))
    instance.tick(0.02)
    generation = instance.gate.generation
    clock.now += 0.11
    ack = instance.apply(command(instance))
    assert ack["status"] == "rejected"
    assert instance.gate.state == "DISARMED"
    assert instance.gate.generation != generation
    assert instance.adapter.calls[-1] == ("stop",)


def test_invalid_current_goal_stops_existing_motion(executor):
    instance, _ = executor
    arm(instance)
    instance.apply(command(instance))
    instance.tick(0.02)
    ack = instance.apply(command(instance, vx=float("nan")))
    assert ack["status"] == "rejected"
    assert instance.gate.state == "DISARMED"
    assert instance.controller.stopped


@pytest.mark.parametrize("fields", [{"vx": float("nan")}])
def test_invalid_new_intent_closes_previous_pending_ack(executor, fields):
    instance, _ = executor
    arm(instance)
    instance.apply(command(instance, request_id="first"))
    instance.apply(command(instance, request_id="invalid", **fields))
    terminal = [row for row in instance.recent_acks if row["request_id"] == "first"]
    assert terminal[-1]["status"] == "rejected"
    assert terminal[-1]["cancelled_by"] == "invalid"
    assert instance.pending is None
