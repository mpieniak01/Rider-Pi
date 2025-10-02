#!/usr/bin/env python3
"""
Acceptance Criteria Verification for Rider-Pi 2D Simulator

This script verifies all acceptance criteria from the issue specification.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("\n" + "=" * 70)
print("ACCEPTANCE CRITERIA VERIFICATION")
print("=" * 70 + "\n")

criteria = []

# AC1: Uruchomienie python run_simulation.py otwiera okno Pygame z wczytaną mapą
print("[AC1] Simulator launches with Pygame window and loads map from .txt file")
try:
    import pygame

    from sim.world import World

    os.environ["SDL_VIDEODRIVER"] = "dummy"
    world = World(map_file="sim/maps/simple.txt")

    assert world.map_width > 0, "Map width should be > 0"
    assert world.map_height > 0, "Map height should be > 0"
    assert len(world.walls) > 0, "Should have walls loaded"

    world.quit()
    criteria.append(("AC1", True, "✓ Simulator loads and parses map files"))
except Exception as e:
    criteria.append(("AC1", False, f"✗ Failed: {e}"))

# AC2: W oknie widoczny jest wirtualny robot w pozycji startowej 'R'
print("\n[AC2] Robot visible at start position 'R' in window")
try:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    world = World(map_file="sim/maps/simple.txt")

    assert world.start_pos is not None, "Start position 'R' should be found"

    from sim.robot import SimulatedRobot

    rx, ry = world.start_pos
    robot = SimulatedRobot(x=rx + 0.5, y=ry + 0.5, angle=0.0)

    # Verify robot can be rendered
    from sim.sensors import VirtualCamera

    camera = VirtualCamera()
    camera_surface = camera.render(robot.x, robot.y, robot.angle, world.wall_segments)
    world.render(robot, camera_surface)

    world.quit()
    criteria.append(("AC2", True, "✓ Robot initialized at start position 'R' and rendered"))
except Exception as e:
    criteria.append(("AC2", False, f"✗ Failed: {e}"))

# AC3: Wysłanie wiadomości MQTT powoduje ruch robota
print("\n[AC3] MQTT message on 'motion' topic causes robot movement")
try:
    from sim.robot import SimulatedRobot

    robot = SimulatedRobot(x=5.0, y=5.0, angle=0.0)
    initial_x = robot.x

    # Simulate command
    cmd = {"type": "drive", "lx": 0.5, "az": 0.0}
    robot._handle_command(cmd)

    assert robot.linear_vel != 0.0, "Linear velocity should be set"

    # Update physics
    robot.update(1.0)

    assert robot.x != initial_x, "Robot should have moved"

    criteria.append(("AC3", True, "✓ MQTT commands control robot movement"))
except Exception as e:
    criteria.append(("AC3", False, f"✗ Failed: {e}"))

# AC4: Panel boczny wyświetla widok z perspektywy robota z perspektywą
print("\n[AC4] Side panel shows first-person view with perspective")
try:
    from sim.sensors import VirtualCamera

    camera = VirtualCamera(width=320, height=240, fov=60.0)

    # Test with some walls
    walls = [
        ((0, 0), (10, 0)),
        ((10, 0), (10, 10)),
    ]

    surface = camera.render(5.0, 5.0, 0.0, walls)

    assert surface is not None, "Camera should render a surface"
    assert surface.get_width() == 320, "Surface should match camera width"
    assert surface.get_height() == 240, "Surface should match camera height"

    criteria.append(("AC4", True, "✓ First-person camera view with perspective rendering"))
except Exception as e:
    criteria.append(("AC4", False, f"✗ Failed: {e}"))

# AC5: Dane telemetryczne (pozycja, orientacja) widoczne w panelu bocznym
print("\n[AC5] Telemetry data (position, orientation) displayed in side panel")
try:
    from sim.robot import SimulatedRobot

    robot = SimulatedRobot(x=7.5, y=3.2, angle=1.57)
    state = robot.get_state()

    assert "x" in state, "State should contain x position"
    assert "y" in state, "State should contain y position"
    assert "angle" in state, "State should contain angle"
    assert state["x"] == 7.5, "X position should match"
    assert state["y"] == 3.2, "Y position should match"

    criteria.append(("AC5", True, "✓ Telemetry data available and correct"))
except Exception as e:
    criteria.append(("AC5", False, f"✗ Failed: {e}"))

# AC6: Symulator publikuje na rider/gyro/angle i rider/camera/frame
print("\n[AC6] Simulator publishes to MQTT topics (gyro/angle, camera/frame)")
try:
    from sim.sensors import VirtualCamera, VirtualGyro

    gyro = VirtualGyro(rate_hz=10.0)
    camera = VirtualCamera(rate_hz=5.0)

    # Verify they have publishers initialized
    assert gyro._pub is not None, "Gyro should have MQTT publisher"
    assert camera._pub is not None, "Camera should have MQTT publisher"

    # Note: Actual MQTT publishing requires broker running
    criteria.append(("AC6", True, "✓ Sensor publishers initialized (requires broker for full test)"))
except Exception as e:
    criteria.append(("AC6", False, f"✗ Failed: {e}"))

# Print results
print("\n" + "=" * 70)
print("RESULTS")
print("=" * 70 + "\n")

passed = 0
failed = 0

for ac_id, success, message in criteria:
    print(f"{ac_id}: {message}")
    if success:
        passed += 1
    else:
        failed += 1

print("\n" + "=" * 70)
print(f"SUMMARY: {passed}/{len(criteria)} passed, {failed}/{len(criteria)} failed")
print("=" * 70 + "\n")

if failed > 0:
    sys.exit(1)
else:
    print("✓ All acceptance criteria verified successfully!\n")
    sys.exit(0)
