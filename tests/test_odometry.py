"""Pure mathematical fixtures; numbers below are fictional, never robot calibration."""

import math
from types import SimpleNamespace

import pytest

from apps.odometry.main import Odometry, OdometryEstimator, normalize_angle
from common.motion_mapping import MAPPING_ID

MOCK_CALIBRATION = {
    "schema_version": 1,
    "manual_verified": True,
    "measurement_id": "fictional-unit-fixture",
    "conditions": {
        "command_mapping": MAPPING_ID,
        "firmware": "fake",
        "surface": "fake",
        "load": "fake",
        "battery": "fake",
    },
    "imu_yaw_sign": 1,
    "linear_m_s": {"1": 0.2, "-1": -0.2},
    "turn_rad_s": {"20": 1.0, "-20": -1.0},
}


@pytest.fixture
def estimator():
    clock = SimpleNamespace(now=1000.0)
    instance = OdometryEstimator(calibration=MOCK_CALIBRATION, clock=lambda: clock.now, wall_clock=lambda: clock.now)
    assert instance.set_reference(
        reference_id="fake-origin",
        operator_consent=True,
        home_operator_confirmed=True,
        home_x=0,
        home_y=0,
    )
    instance.update_imu(0.0, observed_at=clock.now)
    return instance, clock


def output(clock, **fields):
    return {
        "source": "motion-executor",
        "accepted": True,
        "generation": "fake-generation",
        "instance_id": "fake-executor",
        "linear_step": 1,
        "turn_step": 0,
        "stopped": False,
        "observed_at": clock.now,
        **fields,
    }


def executor_state(instance, clock, **fields):
    return {
        "contract_version": 1,
        "state": "DISARMED",
        "ready": True,
        "hardware_ready": True,
        "error": None,
        "uart_owner": "motion-executor",
        "instance_id": "fake-executor",
        "generation": "fake-generation",
        "moving": False,
        "target": {"lx": 0.0, "az": 0.0},
        "output": {"lx": 0.0, "az": 0.0},
        "sdk_output": dict(instance.output or {}),
        "observed_at": clock.now,
        **fields,
    }


def accept_stop(instance, clock):
    assert instance.update_output(output(clock, linear_step=0, stopped=True))
    assert instance.update_executor_state(executor_state(instance, clock))


@pytest.mark.parametrize(
    "angle,expected",
    [
        (0, 0),
        (math.pi / 2, math.pi / 2),
        (3 * math.pi / 2, -math.pi / 2),
        (-3 * math.pi / 2, math.pi / 2),
        (2 * math.pi, 0),
    ],
)
def test_normalize_angle(angle, expected):
    assert normalize_angle(angle) == pytest.approx(expected)


def test_requested_commands_are_not_motion_evidence(estimator):
    instance, _ = estimator
    assert not instance.update_motion_command(1.0, 1.0)
    assert not instance.update_pose(0.1)
    assert instance.x == instance.y == 0


def test_recorded_sdk_step_updates_model(estimator):
    instance, clock = estimator
    assert instance.update_output(output(clock))
    for _ in range(3):
        clock.now += 0.05
        assert instance.update_pose(0.05)
    assert instance.x == pytest.approx(0.03)
    assert instance.get_pose()["confidence"] is None
    assert instance.get_pose()["physical_completion"] == "unverified"


def test_current_reference_without_home_keeps_data_separate_from_navigation(estimator):
    instance, clock = estimator
    instance.update_output(output(clock, linear_step=0, stopped=True))
    assert instance.set_reference(reference_id="position-only", operator_consent=True)
    assert instance.quality()["data_ready"] and not instance.quality()["navigation_ready"]
    assert instance.home is None and instance.quality()["navigation_error"] == "current_confirmed_home_required"


def test_heading_and_negative_sdk_step(estimator):
    instance, clock = estimator
    instance.theta = math.pi / 2
    instance.update_output(output(clock, linear_step=-1))
    instance.update_pose(0.1)
    assert instance.x == pytest.approx(0)
    assert instance.y == pytest.approx(-0.02)


def test_imu_delta_and_wraparound(estimator):
    instance, clock = estimator
    instance.last_imu_yaw = None
    instance.update_imu(170.0, observed_at=clock.now)
    clock.now += 0.1
    instance.update_imu(-170.0, observed_at=clock.now)
    assert instance.theta == pytest.approx(math.radians(20))


def test_no_calibration_or_current_reference_never_navigation_ready():
    assert not OdometryEstimator(calibration={}).get_pose()["navigation_ready"]
    assert not OdometryEstimator(calibration=MOCK_CALIBRATION).reference_verified


@pytest.mark.parametrize(
    "fields",
    [
        {"accepted": False},
        {"observed_at": 999},
        {"linear_step": None},
        {"linear_step": 1.0},
        {"turn_step": True},
        {"source": "manual"},
        {"generation": None},
        {"stopped": True},
    ],
)
def test_invalid_output_does_not_integrate(estimator, fields):
    instance, clock = estimator
    assert not instance.update_output(output(clock, **fields))
    assert not instance.update_pose(0.1)
    assert instance.x == 0


def test_output_timeout_and_clock_rollback_are_sticky_after_movement(estimator):
    instance, clock = estimator
    instance.update_output(output(clock))
    instance.update_pose(0.1)
    clock.now += 0.3
    assert not instance.update_pose(0.1)
    position = instance.x
    clock.now -= 0.3
    instance.update_output(output(clock))
    instance.update_imu(0, observed_at=clock.now)
    assert not instance.update_pose(0.1)
    assert instance.x == position


@pytest.mark.parametrize("dt", [0, -0.1, 0.3, float("nan"), float("inf"), True])
def test_invalid_dt_never_moves_model(estimator, dt):
    instance, clock = estimator
    instance.update_output(output(clock))
    assert not instance.update_pose(dt)
    assert instance.x == 0


def test_stop_and_unmeasured_steps(estimator):
    instance, clock = estimator
    instance.update_output(output(clock))
    instance.update_pose(0.1)
    clock.now += 0.05
    instance.update_output(output(clock, linear_step=0, stopped=True))
    instance.update_pose(0.1)
    assert instance.x == pytest.approx(0.02)
    assert not instance.update_output(output(clock, linear_step=2))
    assert instance.get_pose()["error"] == "sdk_step_unmeasured"


def test_imu_original_time_required_and_order_checked(estimator):
    instance, clock = estimator
    assert not instance.update_imu(0.0)
    assert not instance.update_imu(float("nan"), observed_at=clock.now)
    assert not instance.update_imu(1.0, observed_at=clock.now - 0.1)


def test_motion_before_first_integration_and_imu_loss_requires_reference(estimator):
    instance, clock = estimator
    instance.update_output(output(clock))
    instance.update_imu(None, observed_at=clock.now)
    instance.update_imu(0.0, observed_at=clock.now)
    assert not instance.update_pose(0.1)
    assert instance.get_pose()["error"]
    assert instance.set_reference(reference_id="fresh-manual", operator_consent=True) is False  # SDK still moving.


def test_new_executor_instance_invalidates_reference(estimator):
    instance, clock = estimator
    instance.update_output(output(clock, linear_step=0, stopped=True))
    instance.update_output(output(clock, linear_step=0, stopped=True, instance_id="replacement"))
    assert not instance.reference_verified and instance.reference_id is None
    assert instance.get_pose()["error"] == "executor_instance_changed"


def test_fresh_replacement_cannot_hide_unobserved_output_gap(estimator):
    instance, clock = estimator
    instance.update_output(output(clock))
    clock.now += 0.3
    instance.update_output(output(clock))
    assert not instance.get_pose()["navigation_ready"]
    assert instance.continuity_error == "output_gap_before_replacement"


def test_generation_change_without_observed_stop_breaks_continuity(estimator):
    instance, clock = estimator
    instance.update_output(output(clock))
    instance.update_output(output(clock, generation="new-lease"))
    assert instance.continuity_error == "motion_generation_changed_without_stop"


def test_invalid_sample_cannot_hide_new_executor_identity(estimator):
    instance, clock = estimator
    instance.update_output(output(clock, linear_step=0, stopped=True))
    instance.update_output({})
    instance.update_output(output(clock, linear_step=0, stopped=True, instance_id="replacement"))
    assert not instance.reference_verified


def test_bus_projection_uses_output_topic_and_preserves_source(monkeypatch):
    subscriptions, sent = [], []
    monkeypatch.setattr("apps.odometry.main.BusSub", lambda topic: subscriptions.append(topic) or SimpleNamespace())
    monkeypatch.setattr("apps.odometry.main.BusPub", lambda: SimpleNamespace(publish=lambda *a, **kw: sent.append(a)))
    monkeypatch.setattr(
        "apps.odometry.reference.ReferenceControl", lambda *a: SimpleNamespace(publish_status=lambda: None)
    )
    odometry = Odometry()
    odometry._handle_motion_command({"type": "drive", "lx": 1, "az": 1})
    odometry._publish_pose()
    assert subscriptions == ["motion.output", "motion.state", "imu.data", "odometry.reference"]
    assert sent[0][1]["observed_at"] is None
    assert not sent[0][1]["navigation_ready"]


@pytest.mark.parametrize("message", [[b"motion.output", b'{"accepted":true}'], ("motion.output", {"accepted": True})])
def test_recv_shapes(message):
    topic, row = Odometry._recv_safe(SimpleNamespace(recv=lambda **kw: message), 0)
    assert topic == "motion.output" and row == {"accepted": True}
