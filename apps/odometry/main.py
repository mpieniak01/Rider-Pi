#!/usr/bin/env python3
"""Bounded dead reckoning from accepted SDK output and original IMU samples.

This is a model estimate, not a localization sensor. Without manually recorded
step rates and a current reference, navigation remains unavailable.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time

from apps.odometry.calibration import calibration_status, load_calibration, measured_rate
from common.bus import TOPIC_IMU_DATA, TOPIC_ROBOT_POSE, BusPub, BusSub
from common.data_quality import finite_number, sample_status

LOG = logging.getLogger("odometry")
OUTPUT_MAX_AGE_S = 0.25
IMU_MAX_AGE_S = 2.5
MAX_DT_S = 0.2


def normalize_angle(angle):
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


class OdometryEstimator:
    def __init__(self, x=0.0, y=0.0, theta=0.0, *, calibration=None, clock=time.monotonic, wall_clock=time.time):
        self.clock, self.wall_clock = clock, wall_clock
        self.calibration = load_calibration() if calibration is None else calibration
        self.calibration_error = calibration_status(self.calibration)
        self.x, self.y, self.theta = x, y, normalize_angle(theta)
        self.output = self.imu = None
        self.last_imu_yaw = None
        self.last_imu_ts = None
        self.imu_available = False
        self.last_lx = self.last_az = 0.0
        self.last_motion_ts = None
        self.output_received_at = self.imu_received_at = None
        self.continuity_error = None
        self.reference_verified = False
        self.reference_id = None
        self.home = None
        self._has_moved = False
        self._executor_instance = None

    def set_reference(
        self,
        *,
        reference_id,
        operator_consent=False,
        x=0.0,
        y=0.0,
        theta=0.0,
        home_operator_confirmed=False,
        home_x=None,
        home_y=None,
    ):
        """In-process reference after a manual position check; never restored."""
        if operator_consent is not True or not isinstance(reference_id, str) or not reference_id.strip():
            return False
        if self.last_lx != 0 or self.last_az != 0:
            return False
        if self.output is not None and self.output.get("stopped") is not True:
            return False
        if not all(finite_number(value) for value in (x, y, theta)):
            return False
        if (
            type(home_operator_confirmed) is not bool
            or (home_operator_confirmed and not all(finite_number(value) for value in (home_x, home_y)))
            or (not home_operator_confirmed and (home_x is not None or home_y is not None))
        ):
            return False
        self.x, self.y, self.theta = x, y, normalize_angle(theta)
        self.reference_verified = True
        self.reference_id = reference_id
        self.home = (
            {
                "x": home_x,
                "y": home_y,
                "operator_confirmed": True,
                "reference_id": reference_id,
                "calibration_id": self.calibration.get("measurement_id"),
            }
            if home_operator_confirmed
            else None
        )
        self.continuity_error = None
        self._has_moved = False
        self.last_imu_yaw = None
        return True

    def update_motion_command(self, lx, az):
        # Retained import/interface for legacy callers: requested values are not
        # proof that SDK executed a write, and cannot update physical odometry.
        return False

    def update_output(self, payload):
        previous = self.output.get("observed_at") if self.output else None
        status = sample_status(payload, max_age_s=OUTPUT_MAX_AGE_S, now=self.wall_clock(), previous_ts=previous)
        valid = status["ready"] and payload.get("accepted") is True and payload.get("source") == "motion-executor"
        valid = valid and isinstance(payload.get("generation"), str) and bool(payload["generation"])
        valid = valid and isinstance(payload.get("instance_id"), str) and bool(payload["instance_id"])
        valid = valid and all(type(payload.get(key)) is int for key in ("linear_step", "turn_step"))
        valid = valid and type(payload.get("stopped")) is bool
        if not valid:
            self.last_lx = self.last_az = 0.0
            self.output = None
            if self._has_moved:
                self.continuity_error = status["error"] or "sdk_output_unconfirmed"
            return False
        if payload["stopped"] and (payload["linear_step"] != 0 or payload["turn_step"] != 0):
            self.output = None
            self.last_lx = self.last_az = 0.0
            self.continuity_error = "inconsistent_sdk_stop"
            return False
        if self._executor_instance is not None and payload["instance_id"] != self._executor_instance:
            self.reference_verified = False
            self.reference_id = None
            self.home = None
            self.continuity_error = "executor_instance_changed"
        self._executor_instance = payload["instance_id"]
        if self.output is not None:
            old = sample_status(self.output, max_age_s=OUTPUT_MAX_AGE_S, now=self.wall_clock())
            if (
                payload["generation"] != self.output["generation"]
                and not self.output["stopped"]
                and not payload["stopped"]
            ):
                self.continuity_error = "motion_generation_changed_without_stop"
            elif self._has_moved and (not old["ready"] or self.clock() - self.output_received_at > OUTPUT_MAX_AGE_S):
                self.continuity_error = "output_gap_before_replacement"
        self.output = dict(payload)
        self.output_received_at = self.clock()
        self.last_motion_ts = status["observed_at"]
        self._has_moved = self._has_moved or payload["linear_step"] != 0 or payload["turn_step"] != 0
        if self.calibration_error:
            self.last_lx = self.last_az = 0.0
            return True
        linear = measured_rate(self.calibration, "linear_m_s", payload["linear_step"])
        turn = measured_rate(self.calibration, "turn_rad_s", payload["turn_step"])
        if linear is None or turn is None:
            self.last_lx = self.last_az = 0.0
            self.continuity_error = "sdk_step_unmeasured"
            return False
        self.last_lx, self.last_az = linear, turn
        return True

    def update_imu(self, yaw, *, observed_at=None, payload=None):
        row = dict(payload or {}, yaw=yaw, observed_at=observed_at)
        status = sample_status(row, max_age_s=IMU_MAX_AGE_S, now=self.wall_clock(), previous_ts=self.last_imu_ts)
        if not status["ready"] or not finite_number(yaw):
            self.imu_available = False
            self.imu = None
            if self._has_moved:
                self.continuity_error = status["error"] or "imu_invalid"
            return False
        sign = self.calibration.get("imu_yaw_sign") if not self.calibration_error else None
        yaw_rad = math.radians(yaw) * sign if sign is not None else None
        if yaw_rad is not None and self.last_imu_yaw is not None and observed_at > self.last_imu_ts:
            self.theta = normalize_angle(self.theta + normalize_angle(yaw_rad - self.last_imu_yaw))
        self.last_imu_yaw = yaw_rad
        self.last_imu_ts = observed_at
        self.imu_received_at = self.clock()
        self.imu = row
        self.imu_available = True
        return True

    def quality(self):
        output = sample_status(self.output, max_age_s=OUTPUT_MAX_AGE_S, now=self.wall_clock())
        imu = sample_status(self.imu, max_age_s=IMU_MAX_AGE_S, now=self.wall_clock())
        error = self.calibration_error or self.continuity_error
        if not error and not self.reference_verified:
            error = "current_manual_reference_required"
        if not error:
            error = output["error"] or imu["error"]
        # A wall-clock adjustment cannot make old arrivals fresh again.
        for received, budget in ((self.output_received_at, OUTPUT_MAX_AGE_S), (self.imu_received_at, IMU_MAX_AGE_S)):
            if received is None or not 0 <= self.clock() - received <= budget:
                error = error or "source_arrival_stale"
        observed = min(output["observed_at"], imu["observed_at"]) if output["ready"] and imu["ready"] else None
        return {
            "data_ready": error is None,
            "navigation_ready": error is None and self.home is not None,
            "navigation_error": error or ("current_confirmed_home_required" if self.home is None else None),
            "error": error,
            "observed_at": observed,
            "calibration_id": self.calibration.get("measurement_id"),
            "reference_id": self.reference_id,
            "home": self.home,
            "confidence": None,
            "confidence_kind": "unquantified_model",
            "physical_completion": "unverified",
            "model": "recorded_sdk_steps_dead_reckoning",
        }

    def update_pose(self, dt):
        valid_dt = finite_number(dt) and 0 < dt <= MAX_DT_S
        quality = self.quality()
        if not valid_dt or not quality["data_ready"]:
            self.last_lx = self.last_az = 0.0
            if self._has_moved or (not valid_dt and self.reference_verified):
                self.continuity_error = "integration_dt_invalid" if not valid_dt else quality["error"]
            return False
        self.x += self.last_lx * math.cos(self.theta) * dt
        self.y += self.last_lx * math.sin(self.theta) * dt
        # Fresh IMU is mandatory; no automatic fall back to guessed turn rates.
        self._has_moved = self._has_moved or self.last_lx != 0 or self.last_az != 0
        return True

    def get_pose(self):
        return {
            "x": self.x,
            "y": self.y,
            "theta": self.theta,
            "theta_deg": math.degrees(self.theta),
            "ts": self.wall_clock(),
            **self.quality(),
        }


class Odometry:
    def __init__(self):
        self.estimator = OdometryEstimator()
        self.sub_motion = BusSub("motion.output")
        self.sub_imu = BusSub(TOPIC_IMU_DATA)
        self.sub_reference = BusSub("odometry.reference")
        self.pub = BusPub()
        self.update_period, self.publish_period = 0.1, 0.2
        self.last_update_ts = self.last_publish_ts = time.monotonic()
        from apps.odometry.reference import ReferenceControl

        self.reference = ReferenceControl(self.estimator, self.pub)

    @staticmethod
    def _decode_payload(payload):
        if isinstance(payload, dict):
            return payload
        try:
            value = json.loads(payload) if isinstance(payload, (bytes, bytearray, str)) else None
            return value if isinstance(value, dict) else None
        except (ValueError, TypeError, UnicodeDecodeError):
            return None

    @staticmethod
    def _normalize_topic(topic):
        return (
            topic.decode(errors="ignore")
            if isinstance(topic, (bytes, bytearray))
            else topic
            if isinstance(topic, str)
            else ""
        )

    @staticmethod
    def _recv_safe(sub, timeout_ms):
        message = sub.recv(timeout_ms=timeout_ms)
        if isinstance(message, (list, tuple)) and len(message) >= 2:
            return Odometry._normalize_topic(message[0]), Odometry._decode_payload(message[-1])
        return "", Odometry._decode_payload(message[0] if isinstance(message, (list, tuple)) and message else message)

    def _handle_motion_command(self, payload):
        # Legacy entry point accepts only executor output shape.
        self.estimator.update_output(payload)

    def _handle_imu_data(self, payload):
        self.estimator.update_imu(payload.get("yaw"), observed_at=payload.get("observed_at"), payload=payload)

    def _publish_pose(self):
        self.pub.publish(TOPIC_ROBOT_POSE, self.estimator.get_pose(), add_ts=False)
        self.last_publish_ts = time.monotonic()
        self.reference.publish_status()

    def run(self):
        try:
            while True:
                topic, row = self._recv_safe(self.sub_motion, 10)
                if topic == "motion.output" and row:
                    self._handle_motion_command(row)
                topic, row = self._recv_safe(self.sub_imu, 10)
                if topic == TOPIC_IMU_DATA and row:
                    self._handle_imu_data(row)
                topic, row = self._recv_safe(self.sub_reference, 0)
                if topic == "odometry.reference" and row:
                    self.reference.apply(row)
                now = time.monotonic()
                if now - self.last_update_ts >= self.update_period:
                    self.estimator.update_pose(now - self.last_update_ts)
                    self.last_update_ts = now
                if now - self.last_publish_ts >= self.publish_period:
                    self._publish_pose()
                time.sleep(0.01)
        finally:
            self.sub_motion.close()
            self.sub_imu.close()
            self.sub_reference.close()
            self.pub.close()


def main():
    logging.basicConfig(level=os.getenv("ODOMETRY_LOG_LEVEL", "INFO"))
    Odometry().run()


if __name__ == "__main__":
    main()
