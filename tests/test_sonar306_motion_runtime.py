"""Runtime characterizations; only existing fake executor, callbacks and clocks."""

import copy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from motion_fakes import arm, command, executor as executor
from test_calibration_profiles import profile as profile, verified
from test_decision_lease import decision, make

from apps.motion import calibration_profiles, config, executor_runtime, telemetry_poll
from apps.motion.rider_control import LEGACY_MOTION_RETIRED, RiderMotion
from apps.motion.sensor_quality import SensorSamples
from common import agent_control


@pytest.mark.parametrize("mode", [0, 1, 2])
def test_controller_timing_rejection_stops_before_nonzero_write(executor, mode):
    instance, _ = executor
    arm(instance)
    assert instance.apply(command(instance))["accepted"]
    instance.controller.limits = replace(instance.controller.limits, ramp_mode=mode)
    before = list(instance.adapter.calls)
    assert instance.controller.tick(float("nan")) is False
    assert instance.adapter.calls == [*before, ("stop",)]
    assert instance.controller.t_lx == instance.controller.o_lx == instance.controller.deadline == 0
    assert instance.gate.reason == "control_timing_invalid"


def test_controller_invalid_mode_does_not_change_target_or_sdk(executor):
    instance, _ = executor
    arm(instance)
    controller = instance.controller
    before = controller.t_lx, controller.t_az, controller.deadline, list(instance.adapter.calls)
    assert not controller.drive(0.1, 0.0, 0.1, mode="unsupported")
    assert (controller.t_lx, controller.t_az, controller.deadline, instance.adapter.calls) == before


def test_executor_burst_bounds_and_passive_filtering():
    rows = [("motion.command", {"action": "move"}), ("passive", {}), ("motion.command", {"action": "stop"})]
    rows += [("motion.command", {"action": "move"})] * 70
    events = []

    def recv(*, timeout_ms):
        events.append(timeout_ms)
        return rows.pop(0)

    result = executor_runtime._receive_burst(SimpleNamespace(recv=recv), {"motion.command"})
    assert events == [20] + [0] * 63
    assert len(result) == 63 and result[1][1]["action"] == "stop" and len(rows) == 9


def test_dual_sensor_clocks_deny_rollback_without_fabricating_measurement():
    clocks = SimpleNamespace(mono=100, wall=1000)
    samples = SensorSamples(lambda: clocks.mono, lambda: clocks.wall, instance_id="fake")
    for name in ("roll", "pitch", "yaw", "battery"):
        samples.observe(name, 0.5)
    assert samples.quality()["ready"]
    clocks.wall = 999
    result = samples.quality()
    assert result["error"] == "sensor_quality:roll,pitch,yaw,battery"
    assert result["sensors"]["battery"]["value"] is None
    assert samples.rows["battery"]["observed_at"] == 1000
    clocks.wall, clocks.mono = 1000, 103
    assert not samples.quality()["ready"]


def test_named_telemetry_reads_one_packet_with_original_measurement_time(executor, monkeypatch):
    instance, clock = executor
    events = []
    instance.last_firmware = clock()
    instance.last_sensors = 0
    instance.sensor_index = 0
    instance.adapter.extended_sensor_reads = True
    monkeypatch.setattr(
        instance.adapter,
        "read_sensor",
        lambda name: events.append(name) or {"roll": 1, "pitch": 2, "yaw": 3},
        raising=False,
    )
    telemetry_poll.poll(instance)
    assert events == ["imu_packet"] and instance.sensor_index == 1
    assert instance.samples.rows["roll"]["observed_at"] == clock()
    assert instance.samples.rows["accel_x"]["value"] is None
    telemetry_poll.poll(instance)
    assert events == ["imu_packet"]


def test_tracking_config_applies_known_fields_then_environment(monkeypatch):
    monkeypatch.setattr(config, "_read_toml", lambda _: {"tracking": {"kp": 0.2, "cmd_prio": 5, "unknown": 2}})
    monkeypatch.setenv("TRACKING_KP", "0.3")
    monkeypatch.setenv("TRACKING_CMD_PRIO", "7")
    result = config.load_config("/fake/config.toml")
    assert result.kp == 0.3 and result.cmd_prio == 7 and not hasattr(result, "unknown")
    monkeypatch.setenv("TRACKING_KP", "invalid")
    with pytest.raises(ValueError):
        config.load_config("/fake/config.toml")


@pytest.mark.parametrize("method", ["forward", "backward", "left", "right"])
def test_legacy_direct_actuation_remains_retired_without_adapter(method):
    instance = RiderMotion.__new__(RiderMotion)
    with pytest.raises(PermissionError, match=LEGACY_MOTION_RETIRED):
        getattr(instance, method)()


@pytest.mark.parametrize(
    "edits,error",
    [
        ({"schema_version": False, "name": ""}, "profile_schema_version"),
        (
            {"interaction": {"linear_speed": 2, "turn_speed": 0.2, "pulse_duration": 0.1}, "schema_version": False},
            "profile_interaction_linear_speed",
        ),
        ({"measurements": [{"duration_s": -1, "phase": "invalid"}]}, "profile_measurement_duration_s"),
        ({"measurements": [{"phase": "invalid", "sdk_step": True}]}, "profile_measurement_phase"),
    ],
)
def test_profile_schema_error_order_and_no_input_mutation(profile, edits, error):
    profile.update(edits)
    before = copy.deepcopy(profile)
    with pytest.raises(ValueError, match=error):
        calibration_profiles.validate_profile(profile)
    assert profile == before


def test_historical_verification_is_cleared_before_manual_evidence_checks(profile):
    value = verified(profile)
    value["provenance"] = {"kind": "historical", "notes": ""}
    value["measurements"] = []
    before = copy.deepcopy(value)
    result = calibration_profiles.validate_profile(value)
    assert result["odometry"]["manual_verified"] is False and value == before


def test_activation_zero_proof_precedes_envelope_and_does_not_consume_sequence():
    state = {
        "contract_version": 1,
        "state": "DISARMED",
        "moving": False,
        "observed_at": 1000,
        "generation": "g",
        "last_seq": 3,
        "target": {"lx": 0.1, "az": 0},
        "output": {"lx": 0, "az": 0},
    }
    before = copy.deepcopy(state)
    assert (
        calibration_profiles.validate_activate({"generation": "old"}, state, now=1000)
        == "activation_requires_zero_output"
    )
    assert state == before


def test_agent_sequence_errors_precede_bad_timestamp_or_direction():
    body = {k: "id" for k in agent_control.BODY_FIELDS}
    body.update(seq=True, ttl_ms=501, settings_revision=-1, ts=float("nan"), direction="invalid")
    before = copy.copy(body)
    with pytest.raises(ValueError, match="agent_sequence_invalid"):
        agent_control.validate_body(body)
    assert body == before


@pytest.mark.parametrize(
    "edits,error,consumed",
    [
        ({"run_id": "other", "valid_for_ms": False}, "decision_invalid_or_expired", False),
        ({"valid_for_ms": False, "action": "bad"}, "decision_invalid_or_expired", False),
        ({"action": "bad", "state": "unknown"}, "decision_invalid_action", False),
        ({"state": "unknown", "clear_count": 0}, "decision_not_authorized", True),
    ],
)
def test_decision_validation_precedence_never_calls_drive(edits, error, consumed):
    lease, _, calls = make()
    assert not lease.accept(decision(**edits), "f1", 1, 0)
    assert lease.reason == error and calls == [("stop",)]
    assert lease.last_seq == (1 if consumed else -1)
    assert lease.deadline is None and lease.moving is False


def test_decision_callback_failure_latches_and_clears_permit():
    lease, _, calls = make()

    def fail(*_):
        raise OSError("fake submit failure")

    lease.drive = fail
    with pytest.raises(OSError, match="fake submit failure"):
        lease.accept(decision(), "f1", 1, 0)
    assert lease.reason == "motion_submission_failed" and lease.latched
    assert lease.deadline is None and lease.feedback_deadline is None and not lease.moving
    assert calls == [("stop",)]
