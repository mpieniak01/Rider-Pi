"""Idle continuity/order fixtures: only fake SDK, clocks and in-memory BUS."""

from types import SimpleNamespace

import pytest
from motion_fakes import arm, command, executor as executor
from test_odometry import MOCK_CALIBRATION, accept_stop, estimator as estimator, executor_state, output

from apps.odometry.main import OdometryEstimator


def test_accepted_stop_remains_idle_model_with_live_executor_and_imu(estimator):
    instance, clock = estimator
    instance.update_output(output(clock))
    assert instance.update_pose(0.1)
    clock.now += 0.05
    accept_stop(instance, clock)
    stopped_at, position = instance.output["observed_at"], instance.x
    for _ in range(10):
        clock.now += 1.0
        assert instance.update_executor_state(executor_state(instance, clock))
        assert instance.update_imu(0, observed_at=clock.now)
        assert instance.update_pose(0.1)
        pose = instance.get_pose()
        assert pose["data_ready"]
        assert pose["navigation_ready"]
        assert pose["observed_at"] == clock.now
        assert pose["last_sdk_output_observed_at"] == stopped_at
        assert pose["physical_completion"] == "unverified"
        assert pose["stationary_model_basis"] == "accepted_sdk_zero_and_executor_heartbeat"
    assert instance.output["observed_at"] == stopped_at
    assert instance.x == position
    assert instance._has_moved
    assert instance.continuity_error is None


def test_new_move_after_continuous_idle_is_not_an_output_history_gap(estimator):
    instance, clock = estimator
    instance.update_output(output(clock))
    accept_stop(instance, clock)
    for _ in range(5):
        clock.now += 1
        instance.update_executor_state(executor_state(instance, clock))
        instance.update_imu(0, observed_at=clock.now)
    assert instance.update_output(output(clock))
    assert instance.update_pose(0.1)
    assert instance.continuity_error is None
    assert instance.get_pose()["stationary_model_basis"] is None


def test_state_cannot_supply_or_retimestamp_sdk_stop(estimator):
    instance, clock = estimator
    row = executor_state(instance, clock, sdk_output=output(clock, linear_step=0, stopped=True, observed_at=999.99))
    assert not instance.update_executor_state(row)
    assert not instance.quality()["data_ready"]
    assert not instance.set_reference(reference_id="state-only-stop", operator_consent=True)
    instance.update_output(output(clock, linear_step=0, stopped=True))
    stopped_at = instance.output["observed_at"]
    clock.now += 0.3
    assert not instance.update_executor_state(executor_state(instance, clock))
    assert instance.output["observed_at"] == stopped_at
    assert instance.quality()["observed_at"] is None
    assert not instance.set_reference(reference_id="old-stop", operator_consent=True)


def test_stop_requires_heartbeat_and_current_imu_during_idle(estimator):
    instance, clock = estimator
    instance.update_output(output(clock))
    instance.update_output(output(clock, linear_step=0, stopped=True))
    clock.now += 0.3
    instance.update_imu(0, observed_at=clock.now)
    assert not instance.update_pose(0.1)
    assert instance.continuity_error


def test_current_heartbeat_does_not_hide_missing_imu_after_stop(estimator):
    instance, clock = estimator
    instance.update_output(output(clock))
    accept_stop(instance, clock)
    for _ in range(3):
        clock.now += 1
        instance.update_executor_state(executor_state(instance, clock))
    assert not instance.update_pose(0.1)
    assert instance.continuity_error == "sample_stale_or_future"
    instance.update_imu(0, observed_at=clock.now)
    assert not instance.quality()["data_ready"]


@pytest.mark.parametrize("inspect_before_replacement", [False, True])
def test_heartbeat_history_gap_cannot_be_hidden_by_fresh_replacement(estimator, inspect_before_replacement):
    instance, clock = estimator
    instance.update_output(output(clock))
    accept_stop(instance, clock)
    clock.now += 3.01
    if inspect_before_replacement:
        assert not instance.update_pose(0.1)
    instance.update_executor_state(executor_state(instance, clock))
    instance.update_imu(0, observed_at=clock.now)
    assert not instance.update_pose(0.1)
    assert instance.continuity_error
    instance.update_output(output(clock, linear_step=0, stopped=True))
    instance.update_executor_state(executor_state(instance, clock))
    assert not instance.quality()["data_ready"]
    assert instance.set_reference(reference_id="manual-recovery", operator_consent=True)
    assert instance.quality()["data_ready"]


@pytest.mark.parametrize(
    "fields",
    [
        {"contract_version": True},
        {"contract_version": 0},
        {"state": "UNKNOWN"},
        {"state": []},
        {"ready": False},
        {"hardware_ready": False},
        {"error": "uart_failed"},
        {"data_error": "sensor_failed"},
        {"offline": True},
        {"stale": True},
        {"moving": True},
        {"moving": None},
        {"instance_id": "replacement"},
        {"generation": "replacement"},
        {"uart_owner": "legacy-reader"},
        {"output": {"lx": 0.0005, "az": 0}},
        {"target": {"lx": 1, "az": 0}},
        {"observed_at": 1001.1},
        {"observed_at": 999.9},
    ],
)
def test_broken_idle_state_cannot_recover_reference_by_heartbeat(estimator, fields):
    instance, clock = estimator
    instance.update_output(output(clock))
    accept_stop(instance, clock)
    clock.now += 1
    assert not instance.update_executor_state(executor_state(instance, clock, **fields))
    instance.update_imu(0, observed_at=clock.now)
    assert not instance.quality()["data_ready"]
    instance.update_executor_state(executor_state(instance, clock))
    assert not instance.update_pose(0.1)
    assert instance.continuity_error


@pytest.mark.parametrize(
    "fields",
    [
        {"generation": "new"},
        {"instance_id": "new"},
        {"observed_at": 1001.0},
        {"accepted": False},
        {"linear_step": 1},
        {"linear_step": False},
        {"stopped": False},
    ],
)
def test_reported_sdk_write_must_exactly_match_independent_stop(estimator, fields):
    instance, clock = estimator
    instance.update_output(output(clock))
    accept_stop(instance, clock)
    clock.now += 1
    row = executor_state(instance, clock)
    row["sdk_output"].update(fields)
    assert not instance.update_executor_state(row)
    assert not instance.quality()["data_ready"]


def test_heartbeat_older_than_sdk_stop_never_binds_hold(estimator):
    instance, clock = estimator
    instance.update_output(output(clock, linear_step=0, stopped=True))
    assert not instance.update_executor_state(executor_state(instance, clock, observed_at=clock.now - 0.01))
    clock.now += 0.3
    assert instance.quality()["observed_at"] is None


def test_monotonic_rollback_cannot_extend_accepted_stop(estimator):
    instance, clock = estimator
    accept_stop(instance, clock)
    instance.clock = lambda: 999.0
    clock.now += 0.3
    assert not instance.quality()["data_ready"]


def test_restart_heartbeat_invalidates_reference_even_without_new_sdk_output(estimator):
    instance, clock = estimator
    accept_stop(instance, clock)
    clock.now += 1
    assert not instance.update_executor_state(executor_state(instance, clock, instance_id="new-process"))
    assert not instance.reference_verified
    assert instance.reference_id is None
    assert instance.home is None
    assert instance.continuity_error == "executor_instance_changed"


@pytest.mark.parametrize("fields", [{"generation": "new-lease"}, {"state": "UNKNOWN"}, {"ready": False}])
def test_fresh_old_stop_cannot_confirm_reference_in_incompatible_executor_state(estimator, fields):
    instance, clock = estimator
    accept_stop(instance, clock)
    instance.update_executor_state(executor_state(instance, clock, **fields))
    assert not instance.set_reference(reference_id="incompatible-reference", operator_consent=True)


@pytest.mark.parametrize("state_first", [False, True])
def test_real_executor_deadline_publishes_matching_stop_heartbeat_without_another_write(executor, state_first):
    motion, clock = executor
    instance = OdometryEstimator(calibration=MOCK_CALIBRATION, clock=clock, wall_clock=clock)
    assert instance.set_reference(reference_id="mock-deadline", operator_consent=True)
    instance.update_imu(0, observed_at=clock.now)
    rows = []
    motion.publisher = SimpleNamespace(publish=lambda topic, row, **kw: rows.append((topic, row)))
    motion.adapter.output_status = lambda: {"linear_step": 0 if motion.controller.stopped else 1, "turn_step": 0}

    def consume():
        ordered = sorted(rows, key=lambda pair: pair[0] != ("motion.state" if state_first else "motion.output"))
        for topic, row in ordered:
            if topic == "motion.output":
                instance.update_output(row)
            elif topic == "motion.state":
                instance.update_executor_state(row)
        rows.clear()

    clock.now += 0.11  # Past the executor output publication throttle after its mock initialization.
    arm(motion)
    motion.apply(command(motion, duration=0.1))
    motion.tick(0.02)
    consume()
    assert instance.update_pose(0.02)
    clock.now += 0.11
    motion.tick(0.02)
    assert any(topic == "motion.state" and row["moving"] is False for topic, row in rows)
    consume()
    stopped_at, calls = instance.output["observed_at"], list(motion.adapter.calls)
    clock.now += 0.3
    motion.tick(0.02)
    consume()
    instance.update_imu(0, observed_at=clock.now)
    assert instance.update_pose(0.1)
    assert instance.continuity_error is None
    assert instance.output["observed_at"] == stopped_at
    assert motion.output_observed_at == stopped_at
    assert motion.adapter.calls == calls  # Heartbeat does not write more SDK zero commands.
    assert instance.quality()["physical_completion"] == "unverified"
    for _ in range(4):
        clock.now += 1
        motion.poll_sensors()
        motion.publish_status()
        consume()
        instance.update_imu(0, observed_at=clock.now)
        assert instance.update_pose(0.1)
    arm(motion)
    motion.apply(command(motion))
    clock.now += 0.02
    motion.tick(0.02)
    consume()
    assert instance.update_pose(0.1)
    assert instance.continuity_error is None


def test_executor_heartbeat_does_not_extend_nonzero_output(estimator):
    instance, clock = estimator
    instance.update_output(output(clock))
    assert not instance.update_executor_state(executor_state(instance, clock, moving=True))
    clock.now += 0.3
    instance.update_imu(0, observed_at=clock.now)
    assert not instance.update_pose(0.1)
    assert instance.continuity_error


def pending_state(instance, clock, **fields):
    return executor_state(
        instance,
        clock,
        state="ARMED",
        owner="manual",
        lease_remaining_s=10,
        target={"lx": 0.1, "az": 0},
        **fields,
    )


@pytest.mark.parametrize("state_first", [False, True])
@pytest.mark.parametrize("reported_write", [False, True])
def test_legal_move_after_idle_handles_independent_subscription_order(estimator, state_first, reported_write):
    instance, clock = estimator
    instance.update_output(output(clock))
    accept_stop(instance, clock)
    for _ in range(4):
        clock.now += 1
        instance.update_executor_state(executor_state(instance, clock))
        instance.update_imu(0, observed_at=clock.now)
    clock.now += 0.05
    row = pending_state(instance, clock)
    if reported_write:
        row.update(moving=True, output={"lx": 0.1, "az": 0}, sdk_output=output(clock))
    if not state_first:
        assert instance.update_output(output(clock))
    assert not instance.update_executor_state(row)
    if state_first:
        assert not instance.update_pose(0.1)
        assert instance.quality()["error"] == "sdk_output_pending"
        assert instance.continuity_error is None
        clock.now += 0.05
        assert instance.update_output(output(clock))
    instance.update_imu(0, observed_at=clock.now)
    assert instance.update_pose(0.1)
    assert instance.continuity_error is None
    assert instance.reference_verified


def test_pending_target_never_creates_stop_hold_without_prior_witness(estimator):
    instance, clock = estimator
    instance.update_output(output(clock, linear_step=0, stopped=True))
    assert not instance.update_executor_state(pending_state(instance, clock))
    assert not instance._idle_confirmed
    clock.now += 0.3
    assert not instance.quality()["data_ready"]


@pytest.mark.parametrize("replacement", ["output", "heartbeat", "cancelled"])
def test_pending_transition_cannot_hide_timeout_or_be_extended(estimator, replacement):
    instance, clock = estimator
    instance.update_output(output(clock))
    accept_stop(instance, clock)
    clock.now += 1
    instance.update_executor_state(executor_state(instance, clock))
    instance.update_executor_state(pending_state(instance, clock))
    clock.now += 0.1
    instance.update_executor_state(pending_state(instance, clock))
    clock.now += 0.16
    if replacement == "output":
        instance.update_output(output(clock))
    else:
        row = pending_state(instance, clock) if replacement == "heartbeat" else executor_state(instance, clock)
        instance.update_executor_state(row)
    instance.update_imu(0, observed_at=clock.now)
    assert not instance.update_pose(0.1)
    assert instance.continuity_error


def test_pending_state_after_heartbeat_history_gap_cannot_hide_gap(estimator):
    instance, clock = estimator
    accept_stop(instance, clock)
    clock.now += 3.01
    instance.update_executor_state(pending_state(instance, clock))
    assert not instance._idle_confirmed
    assert instance.continuity_error == "executor_state_gap"
    instance.update_output(output(clock))
    instance.update_imu(0, observed_at=clock.now)
    assert not instance.update_pose(0.1)


@pytest.mark.parametrize("dt", [0, -0.1, 0.3, float("nan")])
def test_pending_output_never_masks_invalid_integration_dt(estimator, dt):
    instance, clock = estimator
    accept_stop(instance, clock)
    instance.update_executor_state(pending_state(instance, clock))
    assert instance.quality()["error"] == "sdk_output_pending"
    assert not instance.update_pose(dt)
    assert instance.continuity_error == "integration_dt_invalid"


@pytest.mark.parametrize("inspect_before_replacement", [False, True])
def test_pending_output_never_masks_imu_history_gap(estimator, inspect_before_replacement):
    instance, clock = estimator
    accept_stop(instance, clock)
    for _ in range(2):
        clock.now += 1
        instance.update_executor_state(executor_state(instance, clock))
    clock.now += 0.45
    instance.update_executor_state(pending_state(instance, clock))
    clock.now += 0.1
    if inspect_before_replacement:
        assert instance.quality()["error"] == "sample_stale_or_future"
        assert not instance.update_pose(0.1)
    instance.update_output(output(clock))
    instance.update_imu(0, observed_at=clock.now)
    assert not instance.update_pose(0.1)
    assert instance.continuity_error


@pytest.mark.parametrize("owner", [None, [], {}, "unknown"])
def test_pending_transition_requires_known_owner_without_schema_exception(estimator, owner):
    instance, clock = estimator
    accept_stop(instance, clock)
    row = pending_state(instance, clock)
    row["owner"] = owner
    assert not instance.update_executor_state(row)
    assert instance.continuity_error
    assert not instance.quality()["data_ready"]
