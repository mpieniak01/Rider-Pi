#!/usr/bin/env python3
"""
Test simulated robot physics and MQTT integration.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sim.robot import SimulatedRobot


def test_robot_initialization():
    """Test that robot initializes with correct state."""
    robot = SimulatedRobot(x=5.0, y=10.0, angle=math.pi / 4)

    assert robot.x == 5.0
    assert robot.y == 10.0
    assert abs(robot.angle - math.pi / 4) < 0.001
    assert robot.linear_vel == 0.0
    assert robot.angular_vel == 0.0

    print("✓ Robot initialization test passed")


def test_robot_physics_linear():
    """Test linear motion physics."""
    robot = SimulatedRobot(x=0.0, y=0.0, angle=0.0)
    robot.linear_vel = 1.0  # 1 m/s forward
    robot.angular_vel = 0.0

    # Update for 1 second
    robot.update(1.0)

    # Should move 1 meter in X direction (angle=0 is right)
    assert abs(robot.x - 1.0) < 0.001
    assert abs(robot.y - 0.0) < 0.001
    assert abs(robot.angle - 0.0) < 0.001

    print("✓ Linear physics test passed")


def test_robot_physics_angular():
    """Test angular motion physics."""
    robot = SimulatedRobot(x=0.0, y=0.0, angle=0.0)
    robot.linear_vel = 0.0
    robot.angular_vel = math.pi / 2  # 90 degrees per second

    # Update for 1 second
    robot.update(1.0)

    # Should rotate 90 degrees (pi/2 radians)
    assert abs(robot.angle - math.pi / 2) < 0.001
    assert abs(robot.x - 0.0) < 0.001
    assert abs(robot.y - 0.0) < 0.001

    print("✓ Angular physics test passed")


def test_robot_physics_combined():
    """Test combined linear and angular motion."""
    robot = SimulatedRobot(x=0.0, y=0.0, angle=0.0)
    robot.linear_vel = 1.0  # 1 m/s
    robot.angular_vel = math.pi / 2  # 90 deg/s

    # Update for 0.5 seconds
    robot.update(0.5)

    # Should move forward while turning
    # After 0.5s: angle = pi/4, moved ~0.5m in initial direction
    assert robot.angle > 0.0  # Has rotated
    assert robot.x > 0.0  # Has moved forward in X
    assert robot.y > 0.0  # Has moved forward in Y (due to rotation)

    print("✓ Combined physics test passed")


def test_command_handling():
    """Test command parsing and handling."""
    robot = SimulatedRobot(x=0.0, y=0.0, angle=0.0)

    # Test drive command
    robot._handle_command({"type": "drive", "lx": 1.0, "az": 0.5})
    assert robot.linear_vel == 0.3  # 1.0 * 0.3
    assert robot.angular_vel == 0.75  # 0.5 * 1.5

    # Test stop command
    robot._handle_command({"type": "stop"})
    assert robot.linear_vel == 0.0
    assert robot.angular_vel == 0.0

    print("✓ Command handling test passed")


def test_robot_state():
    """Test get_state method."""
    robot = SimulatedRobot(x=1.5, y=2.5, angle=0.5)
    robot.linear_vel = 0.2
    robot.angular_vel = 0.3

    state = robot.get_state()

    assert state["x"] == 1.5
    assert state["y"] == 2.5
    assert state["angle"] == 0.5
    assert state["linear_vel"] == 0.2
    assert state["angular_vel"] == 0.3

    print("✓ Robot state test passed")


def test_angle_normalization():
    """Test that angles are normalized to [-pi, pi]."""
    robot = SimulatedRobot(x=0.0, y=0.0, angle=0.0)
    robot.angular_vel = 10.0  # High angular velocity

    # Update for several seconds to accumulate large angle
    for _ in range(10):
        robot.update(1.0)

    # Angle should be normalized to [-pi, pi]
    assert -math.pi <= robot.angle <= math.pi

    print("✓ Angle normalization test passed")


if __name__ == "__main__":
    print("Running SimulatedRobot tests...\n")

    test_robot_initialization()
    test_robot_physics_linear()
    test_robot_physics_angular()
    test_robot_physics_combined()
    test_command_handling()
    test_robot_state()
    test_angle_normalization()

    print("\n✓ All tests passed!")
