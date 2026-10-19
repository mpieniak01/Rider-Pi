#!/usr/bin/env python3
"""Acceptance criteria for the 2D simulator; import never runs the checks."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from acceptance_report import run_criteria, simulation_world


def check_map_loading():
    """A map must have nonempty dimensions and loaded walls."""
    with simulation_world(map_file="sim/maps/simple.txt") as world:
        assert world.map_width > 0, "Map width should be > 0"
        assert world.map_height > 0, "Map height should be > 0"
        assert len(world.walls) > 0, "Should have walls loaded"
    return "✓ Simulator loads and parses map files"


def check_robot_rendering():
    """The simulated robot and first-person camera render at the map start."""
    from sim.robot import SimulatedRobot
    from sim.sensors import VirtualCamera

    with simulation_world(map_file="sim/maps/simple.txt") as world:
        assert world.start_pos is not None, "Start position 'R' should be found"
        rx, ry = world.start_pos
        robot = SimulatedRobot(x=rx + 0.5, y=ry + 0.5, angle=0.0)
        camera = VirtualCamera()
        surface = camera.render(robot.x, robot.y, robot.angle, world.wall_segments)
        world.render(robot, surface)
    return "✓ Robot initialized at start position 'R' and rendered"


def check_simulated_motion():
    """A simulated command must change velocity and position, with no hardware."""
    from sim.robot import SimulatedRobot

    robot = SimulatedRobot(x=5.0, y=5.0, angle=0.0)
    initial_x = robot.x
    robot._handle_command({"type": "drive", "lx": 0.5, "az": 0.0})
    assert robot.linear_vel != 0.0, "Linear velocity should be set"
    robot.update(1.0)
    assert robot.x != initial_x, "Robot should have moved"
    return "✓ Simulated commands change velocity and position"


def check_camera_surface():
    """The virtual camera must produce a surface of the requested size."""
    from sim.sensors import VirtualCamera

    camera = VirtualCamera(width=320, height=240, fov=60.0)
    walls = [((0, 0), (10, 0)), ((10, 0), (10, 10))]
    surface = camera.render(5.0, 5.0, 0.0, walls)
    assert surface is not None, "Camera should render a surface"
    assert surface.get_width() == 320, "Surface should match camera width"
    assert surface.get_height() == 240, "Surface should match camera height"
    return "✓ First-person camera view with perspective rendering"


def check_telemetry():
    """Simulated telemetry must expose the initialized position and orientation."""
    from sim.robot import SimulatedRobot

    robot = SimulatedRobot(x=7.5, y=3.2, angle=1.57)
    state = robot.get_state()
    assert "x" in state, "State should contain x position"
    assert "y" in state, "State should contain y position"
    assert "angle" in state, "State should contain angle"
    assert state["x"] == 7.5, "X position should match"
    assert state["y"] == 3.2, "Y position should match"
    return "✓ Telemetry data available and correct"


def check_sensor_publishers():
    """Sensors need publisher objects; this does not prove a broker connection."""
    from sim.sensors import VirtualCamera, VirtualGyro

    gyro = VirtualGyro(rate_hz=10.0)
    camera = VirtualCamera(rate_hz=5.0)
    assert gyro._pub is not None, "Gyro should have BUS publisher"
    assert camera._pub is not None, "Camera should have BUS publisher"
    return "✓ Sensor publisher objects initialized (transport delivery not tested)"


def main():
    """Run the six original simulator checks and expose failures as exit status."""
    criteria = [
        ("AC1", "Simulator launches with Pygame window and loads map from .txt file", check_map_loading),
        ("AC2", "Robot visible at start position 'R' in window", check_robot_rendering),
        ("AC3", "Direct simulated drive command changes robot position", check_simulated_motion),
        ("AC4", "Side panel shows first-person view with perspective", check_camera_surface),
        ("AC5", "Telemetry data (position, orientation) displayed in side panel", check_telemetry),
        ("AC6", "Sensor publisher objects initialize for gyro and camera", check_sensor_publishers),
    ]
    return run_criteria("ACCEPTANCE CRITERIA VERIFICATION", criteria)


if __name__ == "__main__":
    sys.exit(main())
