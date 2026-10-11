"""Software profile activation only: fake SDK, clocks, files and BUS."""

import copy
import json

import pytest
from motion_fakes import arm, command, executor as executor
from test_odometry import MOCK_CALIBRATION

from apps.motion import calibration_profiles as profiles
from apps.motion.calibration_runtime import CalibrationRuntime
from apps.motion.dynamics import RampLimits
from apps.motion.executor import MotionExecutor
from apps.odometry.main import OdometryEstimator
from apps.odometry.reference import ReferenceControl


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_CALIBRATION_DIR", str(tmp_path / "profiles"))


def profile(*, verified=False, **motion):
    record = copy.deepcopy(MOCK_CALIBRATION)
    record.update(manual_verified=verified, observations={})
    record["conditions"].update(operator="fictional operator", date="fictional date")
    return {
        "schema_version": 1,
        "name": "Fictional isolated profile",
        "provenance": {"kind": "manual" if verified else "draft", "notes": "No physical measurements"},
        "motion": {"speed_limit": 0.4, "linear_rate": 0.5, "turn_rate": 1.0, **motion},
        "odometry": record,
        "measurements": [{"measurement_id": record["measurement_id"], "notes": "Fictional unit fixture"}],
    }


def activation(instance, digest=None, **fields):
    digest = digest or profiles.save_profile(profile())["digest"]
    return command(
        instance,
        "activate_calibration",
        profile_digest=digest,
        operator_consent=True,
        operator_plan="Apply a fictional software profile without any SDK write",
        **fields,
    )


def activate(instance, digest=None, **fields):
    return instance.apply(activation(instance, digest, **fields), topic="calibration.activate")


def estimate(clock):
    return OdometryEstimator(clock=clock, wall_clock=clock)


def test_odometry_activation_preserves_device_motion_settings(executor):
    instance, clock = executor
    before = list(instance.adapter.calls)
    generation = instance.gate.generation
    ack = activate(instance)
    assert ack["status"] == "executed" and ack["actuation"] is False
    assert ack["physical_completion"] == "unverified"
    assert instance.adapter.calls == before
    assert instance.gate.state == "DISARMED" and instance.gate.generation != generation
    assert ack["generation"] == instance.gate.generation and ack["command_generation"] == generation
    assert instance.controller.limits == RampLimits()
    assert instance.controller.limits.watchdog_s == 0.5
    assert profiles.read_active()["activated_at"] == clock.now
    assert instance.snapshot()["calibration"]["profile_digest"] == ack["profile_digest"]
    assert instance.snapshot()["calibration"]["odometry_error"] == "manual_calibration_required"
    assert not instance.snapshot()["can_move"]


@pytest.mark.parametrize("kind", ["armed", "estop", "deadline", "pending", "target", "output", "moving"])
def test_activation_denied_for_nonidle_states_without_sdk(executor, kind):
    instance, _ = executor
    if kind == "armed":
        arm(instance)
    elif kind == "estop":
        instance.gate.latch_estop(persist=False)
    elif kind == "deadline":
        instance.controller.deadline = instance.gate.clock() + 0.1
    elif kind == "pending":
        instance.pending = {"request_id": "pending"}
    elif kind == "target":
        instance.controller.t_lx = 0.01
    elif kind == "output":
        instance.controller.o_az = 0.01
    else:
        instance.controller.stopped = False
    before = list(instance.adapter.calls)
    assert activate(instance)["status"] == "rejected"
    assert profiles.read_active() is None
    assert instance.adapter.calls == before


@pytest.mark.parametrize(
    "fields",
    [
        {"operator_consent": False},
        {"operator_plan": ""},
        {"source": "navigation"},
        {"seq": True},
        {"generation": "previous"},
        {"ttl_ms": 501},
        {"ts": 999},
        {"ts": 1000.01},
        {"action": "arm"},
    ],
)
def test_activation_requires_original_operator_metadata(executor, fields):
    instance, _ = executor
    row = activation(instance)
    row.update(fields)
    before = list(instance.adapter.calls)
    assert instance.apply(row, topic="calibration.activate")["status"] == "rejected"
    assert profiles.read_active() is None
    assert instance.adapter.calls == before


def test_replay_consumed_even_if_profile_missing(executor):
    instance, _ = executor
    row = activation(instance, "a" * 64)
    assert instance.apply(row, topic="calibration.activate")["status"] == "rejected"
    assert instance.gate.last_seq == row["seq"]
    assert instance.apply(row, topic="calibration.activate")["error"] == "stale_sequence"


def test_cap_ceiling_preserved_when_lowering_then_raising(executor):
    instance, _ = executor
    assert activate(instance)["accepted"]
    digest = profiles.save_profile(profile(speed_limit=0.6, linear_rate=1.0, turn_rate=2.0))["digest"]
    assert activate(instance, digest)["accepted"]
    high = profiles.save_profile(profile(linear_rate=instance.calibration.ceilings.linear_rate + 0.01))["digest"]
    assert activate(instance, high)["error"] == "initial_motion_ceiling_exceeded"
    assert instance.controller.limits.linear_rate == 3


def test_invalid_initial_caps_have_no_guessed_recovery(executor):
    instance, _ = executor
    instance.calibration = CalibrationRuntime(RampLimits(linear_rate=float("nan")))
    assert activate(instance)["error"] == "initial_motion_limits_invalid"


def test_activation_can_repair_bad_pointer_without_sensors_or_hardware(executor):
    instance, _ = executor
    root = profiles.storage_dir()
    root.mkdir()
    (root / "active.json").write_text("{}")
    instance.calibration = CalibrationRuntime(instance.controller.limits)
    instance.adapter.error = "persistent_hardware_fault"
    instance.error = "persistent_hardware_fault"
    instance.samples.rows.clear()
    before = list(instance.adapter.calls)
    assert activate(instance)["accepted"]
    assert instance.calibration.error is None
    assert instance.error == "persistent_hardware_fault"
    assert not instance.snapshot()["ready"]
    assert instance.adapter.calls == before


def test_bad_archival_odometry_profile_does_not_override_motion_settings(executor):
    instance, _ = executor
    digest = profiles.save_profile(profile())["digest"]
    profiles.write_active(digest, now=1000)
    (profiles.storage_dir() / "revisions" / (digest + ".json")).write_text("{}")
    instance.calibration = CalibrationRuntime(instance.controller.limits)
    before = list(instance.adapter.calls)
    assert instance.snapshot()["ready"] and arm(instance)["accepted"]
    assert instance.gate.state == "ARMED" and instance.adapter.calls == before


def test_estop_during_persistence_leaves_partial_and_inhibited(executor, monkeypatch):
    instance, _ = executor
    write = profiles.write_active

    def changed(*args, **kwargs):
        pointer = write(*args, **kwargs)
        instance.gate.latch_estop(persist=False)
        return pointer

    monkeypatch.setattr(profiles, "write_active", changed)
    before = list(instance.adapter.calls)
    ack = activate(instance)
    assert ack["error"] == "calibration_state_changed_during_apply"
    with pytest.raises(ValueError, match="active_profile_pending"):
        profiles.read_active()
    assert profiles.read_active(include_pending=True)["profile_digest"] == ack["profile_digest"]
    assert instance.calibration.profile_digest is None and not instance.snapshot()["can_move"]
    assert instance.adapter.calls == before


def test_batch_stop_cancels_activation(executor):
    instance, _ = executor
    row = activation(instance)
    instance.process_batch([("calibration.activate", row), ("motion.command", {"action": "stop"})])
    assert profiles.read_active() is None
    assert instance.gate.state == "DISARMED"


def test_startup_load_does_not_restore_old_consent_or_ack(executor):
    instance, clock = executor
    activate(instance)
    restored = MotionExecutor(gate=instance.gate, adapter=instance.adapter, status_writer=lambda _state: None)
    assert restored.gate.state == "DISARMED"
    assert restored.calibration.source == "saved_profile"
    assert restored.calibration.last_ack is None
    estimator = estimate(clock)
    assert estimator.calibration_state()["error"] == "motion_profile_confirmation_required"
    estimator.update_executor_state(restored.snapshot())
    state = estimator.calibration_state()
    assert state["profile_digest"] == restored.calibration.profile_digest
    assert state["error"] is None and state["source"] == "saved_profile"
    assert state["activation_request_id"] is None and state["command_generation"] is None


def test_live_profile_reset_and_reference_need_fresh_direct_sdk_zero(executor):
    instance, clock = executor
    instance.adapter.output_status = lambda: {"linear_step": 0, "turn_step": 0}
    digest = profiles.save_profile(profile(verified=True))["digest"]
    estimator = estimate(clock)
    assert estimator.set_reference(
        reference_id="old", operator_consent=True, home_operator_confirmed=True, home_x=1, home_y=2
    )
    activate(instance, digest)
    estimator.update_executor_state(instance.snapshot())
    assert estimator.calibration_digest == digest and not estimator.reference_verified
    assert estimator.home is None and estimator.imu is None and estimator.output is None
    assert estimator.continuity_error is None
    assert not estimator.set_reference(reference_id="new", operator_consent=True)
    assert not estimator.update_output(instance.sdk_output())  # old startup zero
    clock.now += 0.01
    instance.controller.stop()  # fake SDK only, explicit separate operator STOP
    assert estimator.update_output(instance.sdk_output())
    estimator.update_executor_state(instance.snapshot())
    estimator.update_imu(0, observed_at=clock.now)
    assert estimator.set_reference(
        reference_id="new", operator_consent=True, home_operator_confirmed=True, home_x=3, home_y=4
    )
    assert estimator.get_pose()["calibration_id"] == digest
    assert estimator.home["calibration_id"] == digest
    assert estimator.get_pose()["measurement_id"] == MOCK_CALIBRATION["measurement_id"]


def test_profile_digest_changes_frame_even_reused_measurement_label(executor):
    instance, clock = executor
    first = profiles.save_profile(profile(verified=True))["digest"]
    second = profiles.save_profile(profile(verified=True, linear_rate=0.4))["digest"]
    assert first != second
    estimator = estimate(clock)
    activate(instance, first)
    estimator.update_executor_state(instance.snapshot())
    estimator.reference_verified, estimator.reference_id, estimator.home = True, "old", {"x": 0, "y": 0}
    activate(instance, second)
    estimator.update_executor_state(instance.snapshot())
    assert estimator.get_pose()["calibration_id"] == second
    assert not estimator.reference_verified and estimator.reference_id is None and estimator.home is None


@pytest.mark.parametrize("failure", ["armed", "future", "wrong_instance", "missing", "bad_ack", "corrupt"])
def test_odom_rejects_unconfirmed_or_unavailable_revision(executor, failure):
    instance, clock = executor
    digest = profiles.save_profile(profile(verified=True))["digest"]
    estimator = estimate(clock)
    activate(instance, digest)
    state = instance.snapshot()
    if failure == "armed":
        state["state"] = "ARMED"
    elif failure == "future":
        state["observed_at"] = clock.now + 1
    elif failure == "wrong_instance":
        state["calibration"]["instance_id"] = "different"
    elif failure == "missing":
        state.pop("calibration")
        estimator.profile_binding.source = "profile"
    elif failure == "bad_ack":
        state["calibration"]["applied_ack"]["command_generation"] = "previous"
    else:
        (profiles.storage_dir() / "revisions" / (digest + ".json")).write_text("{}")
    estimator.update_executor_state(state)
    assert estimator.calibration_state()["error"]
    assert not estimator.reference_verified and not estimator.get_pose()["data_ready"]


def test_reference_status_reports_exact_profile_digest(executor, monkeypatch, tmp_path):
    instance, clock = executor
    estimator = estimate(clock)
    activate(instance)
    estimator.update_executor_state(instance.snapshot())
    monkeypatch.setenv("ODOMETRY_STATE_DIR", str(tmp_path))
    publisher = type("Publisher", (), {"publish": lambda *_args, **_kw: None})()
    reference = ReferenceControl(estimator, publisher, clock=clock)
    reference.publish_status(force=True)
    state = json.loads((tmp_path / "odometry-state.json").read_text())
    assert state["calibration"]["profile_digest"] == instance.calibration.profile_digest
    assert state["calibration"]["activation_request_id"] == instance.calibration.last_ack["request_id"]
    assert state["calibration"]["model_ready"] is False


def test_rejected_attempt_preserves_successful_transaction(executor):
    instance, clock = executor
    good = activate(instance)
    bad = activate(instance, "f" * 64)
    assert bad["status"] == "rejected"
    assert instance.calibration.last_ack == bad and instance.calibration.applied_ack == good
    estimator = estimate(clock)
    estimator.update_executor_state(instance.snapshot())
    assert estimator.calibration_state()["error"] is None
    assert estimator.calibration_state()["profile_digest"] == good["profile_digest"]


def test_configuration_confirmation_separate_from_sensor_failure(executor):
    instance, clock = executor
    activate(instance)
    instance.samples.rows.clear()
    state = instance.snapshot()
    assert state["error"] and not state["ready"]
    estimator = estimate(clock)
    estimator.update_executor_state(state)
    assert estimator.calibration_state()["error"] is None
    assert not estimator.calibration_state()["model_ready"]
    assert not estimator.get_pose()["data_ready"]


def test_late_odometry_can_load_after_generation_rotates(executor):
    instance, clock = executor
    good = activate(instance)
    instance.apply({"action": "stop"})
    assert instance.gate.generation != good["command_generation"]
    estimator = estimate(clock)
    estimator.update_executor_state(instance.snapshot())
    assert estimator.calibration_state()["error"] is None
    assert estimator.calibration_state()["command_generation"] == good["command_generation"]
    assert not estimator.reference_verified


def test_binding_observation_uses_original_motion_heartbeat(executor):
    instance, clock = executor
    activate(instance)
    estimator = estimate(clock)
    estimator.update_executor_state(instance.snapshot())
    initial = estimator.calibration_state()["observed_at"]
    clock.now += 1
    estimator.update_executor_state(instance.snapshot())
    assert estimator.calibration_state()["observed_at"] == clock.now > initial
    clock.now += 1
    assert estimator.calibration_state()["observed_at"] < clock.now


def test_out_of_order_state_never_reloads_old_profile(executor):
    instance, clock = executor
    first = profiles.save_profile(profile())["digest"]
    activate(instance, first)
    old = copy.deepcopy(instance.snapshot())
    estimator = estimate(clock)
    estimator.update_executor_state(old)
    clock.now += 0.1
    second = profiles.save_profile(profile(linear_rate=0.4))["digest"]
    activate(instance, second)
    estimator.update_executor_state(instance.snapshot())
    assert estimator.calibration_digest == second
    estimator.update_executor_state(old)
    assert estimator.calibration_state()["error"] == "motion_profile_unconfirmed"
    assert estimator.calibration == {} and not estimator.get_pose()["data_ready"]
    estimator.update_executor_state(instance.snapshot())
    assert estimator.calibration_digest == second


def test_old_imu_cannot_repopulate_new_revision(executor):
    instance, clock = executor
    estimator = estimate(clock)
    activate(instance)
    estimator.update_executor_state(instance.snapshot())
    assert not estimator.update_imu(0, observed_at=clock.now)
    assert estimator.imu is None
    clock.now += 0.01
    assert estimator.update_imu(0, observed_at=clock.now)


def test_activation_does_not_edit_watchdog_or_dt(executor):
    instance, _ = executor
    limits = RampLimits(watchdog_s=0.3, max_dt_s=0.08)
    instance.calibration = CalibrationRuntime(limits)
    instance.controller.limits = limits
    assert activate(instance)["accepted"]
    assert instance.controller.limits.watchdog_s == 0.3
    assert instance.controller.limits.max_dt_s == 0.08


def test_disk_failure_no_false_applied_or_sdk(executor, monkeypatch):
    instance, _ = executor

    def failed(*_args, **_kwargs):
        raise OSError("mock read-only directory")

    monkeypatch.setattr(profiles, "write_active", failed)
    before = list(instance.adapter.calls)
    ack = activate(instance)
    assert ack["status"] == "rejected" and instance.calibration.applied_ack is None
    assert instance.calibration.profile_digest is None and profiles.read_active() is None
    assert instance.adapter.calls == before


def test_old_queued_arm_cannot_cross_profile_activation(executor):
    instance, _ = executor
    row = activation(instance)
    queued = command(
        instance,
        "arm",
        seq=row["seq"] + 1,
        operator_consent=True,
        operator_plan="Old queued intent must be invalidated",
        owner="manual",
        lease_s=5,
    )
    before = list(instance.adapter.calls)
    instance.process_batch([("calibration.activate", row), ("motion.command", queued)])
    assert instance.last_ack["error"] == "stale_generation"
    assert instance.gate.state == "DISARMED"
    assert instance.adapter.calls == before


@pytest.mark.parametrize("mode", ["live", "sensor_error", "late_stop", "saved"])
def test_actual_runtime_reference_api_pipeline(executor, monkeypatch, tmp_path, mode):
    from services import calibration_api, odometry_api

    instance, clock = executor
    activate(instance)
    if mode == "sensor_error":
        instance.samples.rows.clear()
    elif mode == "late_stop":
        instance.apply({"action": "stop"})
    elif mode == "saved":
        instance = MotionExecutor(gate=instance.gate, adapter=instance.adapter, status_writer=lambda _state: None)
    monkeypatch.setenv("ODOMETRY_STATE_DIR", str(tmp_path / "odometry"))
    monkeypatch.setattr(calibration_api, "read_status", instance.snapshot)
    monkeypatch.setattr(calibration_api, "wall_clock", clock)
    monkeypatch.setattr(calibration_api, "_pending", None)
    monkeypatch.setattr(odometry_api, "wall_clock", clock)
    assert calibration_api.snapshot()["status"] == "partial"  # disabled/missing odometry
    estimator = estimate(clock)
    estimator.update_executor_state(instance.snapshot())
    publisher = type("Publisher", (), {"publish": lambda *_args, **_kw: None})()
    reference = ReferenceControl(estimator, publisher, clock=clock)
    reference.publish_status(force=True)
    real_status = odometry_api.snapshot()
    assert real_status["calibration"]["profile_digest"] == instance.calibration.profile_digest
    status = calibration_api.snapshot()
    assert status["status"] == "applied", status
    assert status["confirmation"] == ("loaded_from_saved" if mode == "saved" else "executed")
    assert not status["model_ready"] and status["physical_completion"] == "unverified"
    if mode == "sensor_error":
        assert status["motion"]["error"] and not status["motion"]["ready"]
    clock.now += 4
    assert calibration_api.snapshot()["status"] == "partial"


@pytest.mark.parametrize("case", ["missing_digest", "wrong_digest", "pending_consumer", "stale_binding", "valid"])
def test_reference_bound_to_exact_confirmed_runtime_profile(executor, monkeypatch, tmp_path, case):
    instance, clock = executor
    instance.adapter.output_status = lambda: {"linear_step": 0, "turn_step": 0}
    digest = profiles.save_profile(profile(verified=True))["digest"]
    estimator = estimate(clock)
    activate(instance, digest)
    if case != "pending_consumer":
        estimator.update_executor_state(instance.snapshot())
    clock.now += 0.01
    instance.controller.stop()  # fake, separate explicit SDK STOP witness
    assert estimator.update_output(instance.sdk_output())
    if case != "pending_consumer":
        estimator.update_executor_state(instance.snapshot())
    estimator.update_imu(0, observed_at=clock.now)
    estimator.reference_verified, estimator.reference_id = True, "previous-reference"
    estimator.home = {"x": 2, "y": 3}
    before = (estimator.reference_verified, estimator.reference_id, dict(estimator.home))
    monkeypatch.setenv("ODOMETRY_STATE_DIR", str(tmp_path / "reference"))
    publisher = type("Publisher", (), {"publish": lambda *_args, **_kw: None})()
    reference = ReferenceControl(estimator, publisher, clock=clock, safety_reader=instance.snapshot)
    row = command(
        instance,
        "reference",
        operator_consent=True,
        operator_plan="Fictional reference position check",
        x=5,
        y=6,
        theta=0,
        profile_digest=digest,
    )
    if case == "missing_digest":
        row.pop("profile_digest")
    elif case == "wrong_digest":
        row["profile_digest"] = "f" * 64
    elif case == "stale_binding":
        estimator.profile_binding.observed_at -= 4
    ack = reference.apply(row)
    if case == "valid":
        assert ack["status"] == "executed" and ack["profile_digest"] == digest
        assert estimator.reference_id == row["request_id"] and estimator.x == 5
    else:
        assert ack["status"] == "rejected" and ack["actuation"] is False
        assert (estimator.reference_verified, estimator.reference_id, estimator.home) == before


def test_same_hash_reapply_requires_current_consumer_transaction(executor, monkeypatch, tmp_path):
    instance, clock = executor
    instance.adapter.output_status = lambda: {"linear_step": 0, "turn_step": 0}
    digest = profiles.save_profile(profile(verified=True))["digest"]
    estimator = estimate(clock)
    activate(instance, digest, request_id="first-activation")
    estimator.update_executor_state(instance.snapshot())
    clock.now += 0.01
    instance.controller.stop()
    assert estimator.update_output(instance.sdk_output())
    estimator.update_executor_state(instance.snapshot())
    estimator.update_imu(0, observed_at=clock.now)
    assert estimator.set_reference(reference_id="previous-reference", operator_consent=True)
    old_transaction = estimator.calibration_state()["applied_generation"]
    activate(instance, digest, request_id="same-hash-new-activation")
    assert instance.calibration.applied_generation != old_transaction
    monkeypatch.setenv("ODOMETRY_STATE_DIR", str(tmp_path / "reference"))
    publisher = type("Publisher", (), {"publish": lambda *_args, **_kw: None})()
    reference = ReferenceControl(estimator, publisher, clock=clock, safety_reader=instance.snapshot)
    row = command(
        instance,
        "reference",
        profile_digest=digest,
        operator_consent=True,
        operator_plan="Fictional manually checked position",
        x=2,
        y=3,
        theta=0,
    )
    assert reference.apply(row)["error"] == "reference_profile_unconfirmed"
    assert estimator.reference_id == "previous-reference"
    estimator.update_executor_state(instance.snapshot())
    assert estimator.reference_id is None
    clock.now += 0.01
    instance.apply({"action": "stop"})  # fake SDK only; stable calibration metadata
    assert estimator.update_output(instance.sdk_output())
    estimator.update_executor_state(instance.snapshot())
    estimator.update_imu(0, observed_at=clock.now)
    row = command(
        instance,
        "reference",
        profile_digest=digest,
        operator_consent=True,
        operator_plan="Fictional manually checked position",
        x=2,
        y=3,
        theta=0,
    )
    ack = reference.apply(row)
    assert ack["status"] == "executed" and ack["profile_digest"] == digest
    assert estimator.reference_id == row["request_id"]
