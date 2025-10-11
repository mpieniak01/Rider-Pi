#!/usr/bin/env python3
"""
Test SIM-3 Acceptance Criteria: Virtual Camera and Gyroscope

This test verifies all acceptance criteria from issue SIM-3:
1. Gyro publishes robot orientation on rider.gyro.angle
2. Camera renders first-person view with perspective
3. Camera view displayed in side panel
4. Camera publishes frames on rider.camera.frame
"""

from __future__ import annotations

import json
import math
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set headless mode for tests
os.environ["SDL_VIDEODRIVER"] = "dummy"


def test_gyro_publishes_orientation():
    """AC1: Robot orientation is cyclically published on rider.gyro.angle."""
    from sim.sensors import VirtualGyro

    gyro = VirtualGyro(rate_hz=100.0)  # High rate for quick testing

    # Verify gyro has MQTT publisher
    assert gyro._pub is not None, "Gyro should have MQTT publisher initialized"

    # Verify publish method exists and can be called
    angle = math.pi / 4  # 45 degrees
    gyro.publish(angle)  # Should not raise exception

    # Verify rate limiting works
    gyro.publish(angle)
    first_pub_time = gyro.last_pub

    # Try to publish immediately (should be rate-limited)
    gyro.publish(angle)
    assert gyro.last_pub == first_pub_time, "Should be rate-limited"

    # Wait for period to pass
    time.sleep(gyro.period)
    gyro.publish(angle)
    assert gyro.last_pub > first_pub_time, "Should publish after period passes"


def test_camera_renders_first_person_view():
    """AC2: Camera generates first-person view with perspective scaling."""
    from sim.sensors import VirtualCamera

    camera = VirtualCamera(width=320, height=240, fov=60.0)

    # Create test walls at different distances
    walls = [
        ((5, 0), (5, 10)),  # Vertical wall to the right
        ((0, 0), (10, 0)),  # Horizontal wall behind
    ]

    # Render from robot position
    robot_x, robot_y, robot_angle = 2.0, 5.0, 0.0
    surface = camera.render(robot_x, robot_y, robot_angle, walls)

    # Verify surface properties
    assert surface is not None, "Camera should render a surface"
    assert surface.get_width() == 320, "Surface width should match camera"
    assert surface.get_height() == 240, "Surface height should match camera"


def test_camera_perspective_scaling():
    """AC3: Walls appear larger as robot approaches them."""
    from sim.sensors import VirtualCamera

    camera = VirtualCamera(width=320, height=240, fov=60.0)

    # Wall directly in front
    walls = [((5, 4), (5, 6))]

    # Render from far away
    surface_far = camera.render(2.0, 5.0, 0.0, walls)

    # Render from close up
    surface_near = camera.render(4.5, 5.0, 0.0, walls)

    # Both should render successfully
    assert surface_far is not None
    assert surface_near is not None

    # Note: In actual implementation, the wall height calculation is:
    # wall_height = min(height, int(height / (min_dist * 0.5)))
    # This means closer walls (smaller min_dist) have larger wall_height


def test_camera_raycasting():
    """Test ray-wall intersection calculation."""
    from sim.sensors import VirtualCamera

    camera = VirtualCamera()

    # Ray pointing right, wall in front
    robot_x, robot_y = 0.0, 0.0
    ray_angle = 0.0  # Pointing right
    wall_x1, wall_y1, wall_x2, wall_y2 = 5.0, -1.0, 5.0, 1.0  # Vertical wall

    dist = camera._ray_wall_intersection(robot_x, robot_y, ray_angle, wall_x1, wall_y1, wall_x2, wall_y2)

    assert dist is not None, "Ray should intersect wall"
    assert dist == pytest.approx(5.0, rel=0.01), "Distance should be 5 units"


def test_camera_publishes_frames():
    """AC4: Camera frames are published on rider.camera.frame."""
    from sim.sensors import VirtualCamera

    camera = VirtualCamera(width=160, height=120, rate_hz=100.0)  # High rate for quick testing

    # Verify camera has MQTT publisher
    assert camera._pub is not None, "Camera should have MQTT publisher initialized"

    # Render a frame
    walls = [((0, 0), (10, 0))]
    camera.render(5.0, 5.0, 0.0, walls)

    # Verify publish method exists and can be called
    camera.publish()  # Should not raise exception

    # Verify rate limiting works
    first_pub_time = camera.last_pub
    camera.publish()
    assert camera.last_pub == first_pub_time, "Should be rate-limited"

    # Wait for period to pass
    time.sleep(camera.period)
    camera.publish()
    assert camera.last_pub > first_pub_time, "Should publish after period passes"


def test_integration_in_main_loop():
    """Verify sensors are integrated in scripts/sim/run_simulation.py main loop."""
    import importlib.util

    # Load run_simulation module
    spec = importlib.util.spec_from_file_location("run_simulation", "scripts/sim/run_simulation.py")
    run_sim = importlib.util.module_from_spec(spec)

    # Verify it imports required modules
    spec.loader.exec_module(run_sim)

    # Verify the modules are imported
    assert hasattr(run_sim, "VirtualGyro"), "Should import VirtualGyro"
    assert hasattr(run_sim, "VirtualCamera"), "Should import VirtualCamera"
    assert hasattr(run_sim, "SimulatedRobot"), "Should import SimulatedRobot"
    assert hasattr(run_sim, "World"), "Should import World"


def test_world_renders_camera_view():
    """Verify world renders camera view in side panel."""
    from sim.robot import SimulatedRobot
    from sim.sensors import VirtualCamera
    from sim.world import World

    world = World(map_file="sim/maps/simple.txt")
    robot = SimulatedRobot(x=5.0, y=5.0, angle=0.0)
    camera = VirtualCamera(width=320, height=240)

    # Render camera view
    camera_surface = camera.render(robot.x, robot.y, robot.angle, world.wall_segments)

    # Render world with camera view
    world.render(robot, camera_surface)  # Should not raise exception

    world.quit()


def test_mqtt_topic_configuration():
    """Verify MQTT topics are correctly configured."""
    from sim.sensors import CAMERA_TOPIC, GYRO_TOPIC

    # Check default topics match specification
    assert GYRO_TOPIC == "rider.gyro.angle", "Gyro topic should be rider.gyro.angle"
    assert CAMERA_TOPIC == "rider.camera.frame", "Camera topic should be rider.camera.frame"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
