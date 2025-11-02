#!/usr/bin/env python3
"""
Unit tests for Odometry module (Rekonesans Stage 2)
"""

import math
import unittest
from unittest.mock import MagicMock, patch

from apps.odometry.main import Odometry, OdometryEstimator, normalize_angle


class TestNormalizeAngle(unittest.TestCase):
    """Test angle normalization function"""

    def test_normalize_angle_in_range(self):
        """Test that angles already in range are unchanged"""
        self.assertAlmostEqual(normalize_angle(0.0), 0.0)
        self.assertAlmostEqual(normalize_angle(math.pi / 2), math.pi / 2)
        self.assertAlmostEqual(normalize_angle(-math.pi / 2), -math.pi / 2)

    def test_normalize_angle_above_pi(self):
        """Test that angles above pi are normalized"""
        self.assertAlmostEqual(normalize_angle(3 * math.pi / 2), -math.pi / 2, places=5)
        self.assertAlmostEqual(normalize_angle(2 * math.pi), 0.0, places=5)

    def test_normalize_angle_below_minus_pi(self):
        """Test that angles below -pi are normalized"""
        self.assertAlmostEqual(normalize_angle(-3 * math.pi / 2), math.pi / 2, places=5)
        self.assertAlmostEqual(normalize_angle(-2 * math.pi), 0.0, places=5)


class TestOdometryEstimator(unittest.TestCase):
    """Test OdometryEstimator functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.estimator = OdometryEstimator(x=0.0, y=0.0, theta=0.0)

    def test_initialization(self):
        """Test estimator initializes with correct values"""
        self.assertEqual(self.estimator.x, 0.0)
        self.assertEqual(self.estimator.y, 0.0)
        self.assertEqual(self.estimator.theta, 0.0)
        self.assertFalse(self.estimator.imu_available)

    def test_initialization_with_pose(self):
        """Test estimator initializes with given pose"""
        estimator = OdometryEstimator(x=1.0, y=2.0, theta=math.pi / 4)
        self.assertEqual(estimator.x, 1.0)
        self.assertEqual(estimator.y, 2.0)
        self.assertAlmostEqual(estimator.theta, math.pi / 4)

    def test_update_motion_command(self):
        """Test updating with motion commands"""
        self.estimator.update_motion_command(0.5, 0.2)
        self.assertEqual(self.estimator.last_lx, 0.5)
        self.assertEqual(self.estimator.last_az, 0.2)

    def test_forward_motion_no_imu(self):
        """Test forward motion updates position correctly without IMU"""
        # Set forward motion command
        self.estimator.update_motion_command(1.0, 0.0)

        # Update pose for 1 second (with default LINEAR_SPEED_SCALE=0.2)
        self.estimator.update_pose(1.0)

        # Should move forward in x direction (0.2 m/s * 1s = 0.2m)
        self.assertAlmostEqual(self.estimator.x, 0.2, places=3)
        self.assertAlmostEqual(self.estimator.y, 0.0, places=3)
        self.assertAlmostEqual(self.estimator.theta, 0.0, places=3)

    def test_rotation_no_imu(self):
        """Test rotation updates orientation without IMU"""
        # Set rotation command (angular speed = 1.0 rad/s with default scale)
        self.estimator.update_motion_command(0.0, 1.0)

        # Update pose for 1 second
        self.estimator.update_pose(1.0)

        # Should rotate by 1.0 radians
        self.assertAlmostEqual(self.estimator.theta, 1.0, places=3)
        self.assertAlmostEqual(self.estimator.x, 0.0, places=3)
        self.assertAlmostEqual(self.estimator.y, 0.0, places=3)

    def test_combined_motion_no_imu(self):
        """Test combined forward and rotation without IMU"""
        # Set combined motion (forward + rotate right)
        self.estimator.update_motion_command(1.0, -0.5)

        # Update pose for 0.5 seconds
        self.estimator.update_pose(0.5)

        # Should have moved forward and rotated
        # Motion model: rotation updates first, then linear motion in new direction
        # Rotation: -0.5 rad/s * 0.5s = -0.25 rad
        # Linear motion: 0.2 m/s * 0.5s = 0.1m in direction theta=-0.25 rad
        # x = 0.1 * cos(-0.25) ≈ 0.097
        # y = 0.1 * sin(-0.25) ≈ -0.025
        self.assertAlmostEqual(self.estimator.x, 0.097, places=2)
        self.assertAlmostEqual(self.estimator.y, -0.025, places=2)
        self.assertAlmostEqual(self.estimator.theta, -0.25, places=3)

    def test_imu_update(self):
        """Test IMU update changes orientation"""
        # First IMU reading establishes baseline
        self.estimator.update_imu(0.0)
        self.assertTrue(self.estimator.imu_available)
        self.assertAlmostEqual(self.estimator.theta, 0.0)

        # Second reading shows 45 degree rotation
        self.estimator.update_imu(45.0)
        self.assertAlmostEqual(self.estimator.theta, math.radians(45.0), places=3)

    def test_imu_wraparound(self):
        """Test IMU handles angle wraparound correctly"""
        # Start at 170 degrees
        self.estimator.update_imu(170.0)

        # Rotate to -170 degrees (20 degree rotation through 180/-180 boundary)
        self.estimator.update_imu(-170.0)

        # The change through wraparound should be 20 degrees (170 -> 180 -> -180 -> -170)
        # So final theta should be approximately 20 degrees (or 0.349 radians)
        # Starting theta after first update is 0 (no change yet)
        # After second update, delta = normalize(-170 - 170) = normalize(-340) = 20 degrees
        self.assertAlmostEqual(self.estimator.theta, math.radians(20.0), places=2)

    def test_forward_motion_with_heading(self):
        """Test forward motion respects current heading"""
        # Set heading to 90 degrees (pointing in +Y direction)
        self.estimator.theta = math.pi / 2

        # Move forward
        self.estimator.update_motion_command(1.0, 0.0)
        self.estimator.update_pose(1.0)

        # Should move in +Y direction, not +X
        self.assertAlmostEqual(self.estimator.x, 0.0, places=3)
        self.assertAlmostEqual(self.estimator.y, 0.2, places=3)

    def test_get_pose(self):
        """Test getting pose returns correct data"""
        self.estimator.x = 1.5
        self.estimator.y = 2.5
        self.estimator.theta = math.pi / 4

        pose = self.estimator.get_pose()

        self.assertEqual(pose["x"], 1.5)
        self.assertEqual(pose["y"], 2.5)
        self.assertAlmostEqual(pose["theta"], math.pi / 4)
        self.assertAlmostEqual(pose["theta_deg"], 45.0, places=1)
        self.assertIn("ts", pose)

    def test_multiple_updates_accumulate(self):
        """Test that multiple pose updates accumulate correctly"""
        # Move forward three times
        self.estimator.update_motion_command(1.0, 0.0)

        for _ in range(3):
            self.estimator.update_pose(0.5)

        # Should have moved 0.2 m/s * 1.5s = 0.3m total
        self.assertAlmostEqual(self.estimator.x, 0.3, places=3)


class TestOdometry(unittest.TestCase):
    """Test Odometry system"""

    def setUp(self):
        """Set up test fixtures"""
        # Mock the bus connections
        self.bus_sub_patch = patch("apps.odometry.main.BusSub")
        self.bus_pub_patch = patch("apps.odometry.main.BusPub")

        self.mock_sub = self.bus_sub_patch.start()
        self.mock_pub = self.bus_pub_patch.start()

        # Create mock instances
        self.mock_sub_motion = MagicMock()
        self.mock_sub_imu = MagicMock()
        self.mock_pub_instance = MagicMock()

        # Return different instances for different topics
        def sub_side_effect(topic):
            if topic == "motion":
                return self.mock_sub_motion
            elif topic == "imu.data":
                return self.mock_sub_imu
            return MagicMock()

        self.mock_sub.side_effect = sub_side_effect
        self.mock_pub.return_value = self.mock_pub_instance

    def tearDown(self):
        """Clean up patches"""
        self.bus_sub_patch.stop()
        self.bus_pub_patch.stop()

    def test_odometry_initialization(self):
        """Test odometry initializes correctly"""
        odometry = Odometry()

        self.assertIsNotNone(odometry.estimator)
        self.assertEqual(odometry.estimator.x, 0.0)
        self.assertEqual(odometry.estimator.y, 0.0)
        self.assertEqual(odometry.estimator.theta, 0.0)

    def test_handle_drive_command(self):
        """Test handling drive motion command"""
        odometry = Odometry()

        cmd = {"type": "drive", "lx": 0.5, "az": 0.2}
        odometry._handle_motion_command(cmd)

        self.assertEqual(odometry.estimator.last_lx, 0.5)
        self.assertEqual(odometry.estimator.last_az, 0.2)

    def test_handle_stop_command(self):
        """Test handling stop motion command"""
        odometry = Odometry()

        # First set some motion
        odometry.estimator.update_motion_command(0.5, 0.2)

        # Then send stop
        cmd = {"type": "stop"}
        odometry._handle_motion_command(cmd)

        self.assertEqual(odometry.estimator.last_lx, 0.0)
        self.assertEqual(odometry.estimator.last_az, 0.0)

    def test_handle_imu_data(self):
        """Test handling IMU data"""
        odometry = Odometry()

        # Send IMU data
        imu_data = {"yaw": 45.0, "pitch": 0.0, "roll": 0.0}
        odometry._handle_imu_data(imu_data)

        # First reading should just initialize
        self.assertTrue(odometry.estimator.imu_available)

    def test_publish_pose(self):
        """Test pose publishing"""
        odometry = Odometry()

        # Set some pose
        odometry.estimator.x = 1.0
        odometry.estimator.y = 2.0
        odometry.estimator.theta = math.pi / 4

        # Publish pose
        odometry._publish_pose()

        # Check that publish was called
        self.mock_pub_instance.publish.assert_called_once()

        # Check topic and payload
        call_args = self.mock_pub_instance.publish.call_args
        topic = call_args[0][0]
        payload = call_args[0][1]

        self.assertEqual(topic, "robot.pose")
        self.assertEqual(payload["x"], 1.0)
        self.assertEqual(payload["y"], 2.0)
        self.assertAlmostEqual(payload["theta"], math.pi / 4)


if __name__ == "__main__":
    unittest.main()
