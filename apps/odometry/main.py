#!/usr/bin/env python3
"""
Odometry - Robot Position Tracking (Rekonesans Stage 2)

Fuses motion commands and IMU data to estimate robot position (x, y, theta).
This is a critical component for mapping (Stage 3) and returning to base (Stage 4).

Architecture:
- Subscribes to motion commands (from navigator or manual control)
- Subscribes to IMU data (actual orientation changes from robot controller)
- Publishes estimated pose (x, y, theta) to robot.pose topic
"""

from __future__ import annotations

import logging
import math
import os
import time

from common.bus import TOPIC_IMU_DATA, TOPIC_MOTION_COMMAND, TOPIC_ROBOT_POSE, BusPub, BusSub

# Environment configuration
LOG_LEVEL = os.getenv("ODOMETRY_LOG_LEVEL", "INFO").upper()
UPDATE_RATE_HZ = float(os.getenv("ODOMETRY_UPDATE_RATE_HZ", "10.0"))
PUBLISH_RATE_HZ = float(os.getenv("ODOMETRY_PUBLISH_RATE_HZ", "5.0"))

# Initial position (can be configured via ENV)
INITIAL_X = float(os.getenv("ODOMETRY_INITIAL_X", "0.0"))
INITIAL_Y = float(os.getenv("ODOMETRY_INITIAL_Y", "0.0"))
INITIAL_THETA = float(os.getenv("ODOMETRY_INITIAL_THETA", "0.0"))

# Motion model parameters (speed scaling factors)
# These convert normalized speeds (0-1) to m/s
LINEAR_SPEED_SCALE = float(os.getenv("ODOMETRY_LINEAR_SPEED_SCALE", "0.2"))  # m/s per unit speed
ANGULAR_SPEED_SCALE = float(os.getenv("ODOMETRY_ANGULAR_SPEED_SCALE", "1.0"))  # rad/s per unit speed

LOG = logging.getLogger("odometry")


def normalize_angle(angle: float) -> float:
    """Normalize angle to [-pi, pi] range"""
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


class OdometryEstimator:
    """Estimates robot pose using motion commands and IMU data"""

    def __init__(self, x: float = 0.0, y: float = 0.0, theta: float = 0.0):
        # Current pose estimate
        self.x = x
        self.y = y
        self.theta = normalize_angle(theta)

        # Last motion command
        self.last_lx = 0.0  # Linear velocity (forward/backward)
        self.last_az = 0.0  # Angular velocity (rotation)
        self.last_motion_ts = time.time()

        # IMU tracking
        self.last_imu_yaw = None
        self.last_imu_ts = None
        self.imu_available = False

        LOG.info(
            f"Odometry initialized at pose: x={self.x:.3f}m, y={self.y:.3f}m, theta={math.degrees(self.theta):.1f}°"
        )

    def update_motion_command(self, lx: float, az: float):
        """Update with new motion command"""
        self.last_lx = lx
        self.last_az = az
        self.last_motion_ts = time.time()

    def update_imu(self, yaw: float):
        """Update with IMU yaw reading (in degrees)"""
        yaw_rad = math.radians(yaw)
        now = time.time()

        if self.last_imu_yaw is None:
            # First IMU reading - just store it
            self.last_imu_yaw = yaw_rad
            self.last_imu_ts = now
            self.imu_available = True
            LOG.debug(f"First IMU reading: yaw={yaw:.1f}°")
            return

        # Calculate change in orientation from IMU
        dt = now - self.last_imu_ts
        if dt > 0 and dt < 1.0:  # Sanity check on dt
            dyaw = normalize_angle(yaw_rad - self.last_imu_yaw)
            # Use IMU data to correct orientation estimate
            self.theta = normalize_angle(self.theta + dyaw)
            LOG.debug(f"IMU update: dyaw={math.degrees(dyaw):.2f}°, new theta={math.degrees(self.theta):.1f}°")

        self.last_imu_yaw = yaw_rad
        self.last_imu_ts = now
        self.imu_available = True

    def update_pose(self, dt: float):
        """Update pose estimate based on motion model"""
        if dt <= 0 or dt > 1.0:
            return  # Sanity check

        # Dead reckoning using motion commands
        # If we have IMU, we trust it for orientation; otherwise use commanded angular velocity
        if not self.imu_available:
            # No IMU - use commanded angular velocity
            dtheta = self.last_az * ANGULAR_SPEED_SCALE * dt
            self.theta = normalize_angle(self.theta + dtheta)

        # Linear motion - apply in current heading direction
        linear_vel = self.last_lx * LINEAR_SPEED_SCALE
        dx = linear_vel * math.cos(self.theta) * dt
        dy = linear_vel * math.sin(self.theta) * dt

        self.x += dx
        self.y += dy

        if abs(dx) > 0.001 or abs(dy) > 0.001 or abs(self.last_az) > 0.01:
            LOG.debug(
                f"Pose update: dx={dx:.4f}m, dy={dy:.4f}m, "
                f"pose=({self.x:.3f}, {self.y:.3f}, {math.degrees(self.theta):.1f}°)"
            )

    def get_pose(self) -> dict:
        """Get current pose estimate"""
        return {
            "x": self.x,
            "y": self.y,
            "theta": self.theta,
            "theta_deg": math.degrees(self.theta),
            "ts": time.time(),
        }


class Odometry:
    """Odometry system - manages pose estimation and bus communication"""

    def __init__(self):
        self.estimator = OdometryEstimator(x=INITIAL_X, y=INITIAL_Y, theta=INITIAL_THETA)

        # Bus connections
        self.sub_motion = BusSub(TOPIC_MOTION_COMMAND)
        self.sub_imu = BusSub(TOPIC_IMU_DATA)
        self.pub = BusPub()

        # Timing
        self.update_period = 1.0 / UPDATE_RATE_HZ
        self.publish_period = 1.0 / PUBLISH_RATE_HZ
        self.last_update_ts = time.time()
        self.last_publish_ts = time.time()

        LOG.info(f"Odometry system initialized (update: {UPDATE_RATE_HZ}Hz, publish: {PUBLISH_RATE_HZ}Hz)")

    def _handle_motion_command(self, payload: dict):
        """Handle incoming motion command"""
        cmd_type = payload.get("type", "")
        if cmd_type == "drive":
            lx = float(payload.get("lx", 0.0))
            az = float(payload.get("az", 0.0))
            self.estimator.update_motion_command(lx, az)
        elif cmd_type == "stop":
            self.estimator.update_motion_command(0.0, 0.0)

    def _handle_imu_data(self, payload: dict):
        """Handle incoming IMU data"""
        yaw = payload.get("yaw")
        if yaw is not None:
            self.estimator.update_imu(float(yaw))

    def _publish_pose(self):
        """Publish current pose estimate"""
        pose = self.estimator.get_pose()
        self.pub.publish(TOPIC_ROBOT_POSE, pose, add_ts=True)
        self.last_publish_ts = time.time()

    def run(self):
        """Main odometry loop"""
        LOG.info("Odometry main loop started")

        try:
            while True:
                now = time.time()

                # Check for motion commands
                topic, payload = self.sub_motion.recv(timeout_ms=10)
                if topic and payload and topic == TOPIC_MOTION_COMMAND:
                    self._handle_motion_command(payload)

                # Check for IMU data
                topic, payload = self.sub_imu.recv(timeout_ms=10)
                if topic and payload and topic == TOPIC_IMU_DATA:
                    self._handle_imu_data(payload)

                # Update pose at configured rate
                if now - self.last_update_ts >= self.update_period:
                    dt = now - self.last_update_ts
                    self.estimator.update_pose(dt)
                    self.last_update_ts = now

                # Publish pose at configured rate
                if now - self.last_publish_ts >= self.publish_period:
                    self._publish_pose()

                # Small sleep to prevent busy waiting
                time.sleep(0.01)

        except KeyboardInterrupt:
            LOG.info("Odometry interrupted by user")
        except Exception as e:
            LOG.exception(f"Error in odometry loop: {e}")
        finally:
            self.sub_motion.close()
            self.sub_imu.close()
            self.pub.close()
            LOG.info("Odometry shutdown complete")


def main():
    """Entry point"""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    odometry = Odometry()
    odometry.run()


if __name__ == "__main__":
    main()
