#!/usr/bin/env python3
"""
Test basic simulator functionality
"""

from __future__ import annotations

import math
import os
import sys
import tempfile

import pytest
from simulator_fixtures import headless_pygame as headless_pygame, robot_factory as robot_factory

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_robot_initialization(robot_factory):
    """Test that robot initializes with correct state."""
    robot = robot_factory(x=5.0, y=10.0, angle=math.pi / 4)

    assert robot.x == 5.0
    assert robot.y == 10.0
    assert robot.angle == math.pi / 4
    assert robot.linear_vel == 0.0
    assert robot.angular_vel == 0.0


def test_robot_update(robot_factory):
    """Test robot physics update."""
    robot = robot_factory(x=0.0, y=0.0, angle=0.0)

    # Set velocities
    robot.linear_vel = 1.0  # 1 m/s
    robot.angular_vel = math.pi / 2  # 90 degrees per second

    # Update for 1 second
    robot.update(1.0)

    # Check that position changed
    assert robot.x != 0.0
    assert robot.angle != 0.0


def test_robot_command_handling(robot_factory):
    """Test robot processes commands correctly."""
    robot = robot_factory()

    # Drive command
    cmd = {"type": "drive", "lx": 0.5, "az": 0.3}
    robot._handle_command(cmd)

    assert robot.linear_vel != 0.0
    assert robot.angular_vel != 0.0

    # Stop command
    cmd = {"type": "stop"}
    robot._handle_command(cmd)

    assert robot.linear_vel == 0.0
    assert robot.angular_vel == 0.0


def test_robot_get_state(robot_factory):
    """Test that robot returns correct state dictionary."""
    robot = robot_factory(x=1.0, y=2.0, angle=0.5)
    state = robot.get_state()

    assert isinstance(state, dict)
    assert "x" in state
    assert "y" in state
    assert "angle" in state
    assert "linear_vel" in state
    assert "angular_vel" in state


def test_map_loading(headless_pygame):
    """Test map file loading."""
    from sim.world import World

    # Create a temporary map file
    map_content = """XXXXX
X R X
X   X
X M X
XXXXX
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(map_content)
        map_file = f.name

    try:
        world = World(map_file=map_file)

        # Check map was loaded
        assert world.map_width > 0
        assert world.map_height > 0
        assert len(world.walls) > 0
        assert world.start_pos is not None
        assert world.goal is not None

        world.quit()
    finally:
        os.unlink(map_file)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
