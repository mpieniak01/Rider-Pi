#!/usr/bin/env python3
"""
Headless test to verify simulator can initialize without display.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Prevent pygame from requiring display
os.environ["SDL_VIDEODRIVER"] = "dummy"

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_simulator_initialization():
    """Test that simulator components can be initialized."""
    print("Testing simulator initialization (headless)...")

    # Test robot
    from sim.robot import SimulatedRobot

    robot = SimulatedRobot(x=5.0, y=5.0, angle=0.0)
    assert robot.x == 5.0
    print("✓ Robot initialized")

    # Test sensors
    from sim.sensors import VirtualCamera, VirtualGyro

    _ = VirtualGyro(rate_hz=10.0)
    print("✓ Gyro initialized")

    _ = VirtualCamera(width=320, height=240)
    print("✓ Camera initialized")

    # Test world
    from sim.world import World

    map_file = "sim/maps/simple.txt"
    world = World(map_file=map_file, cell_size=40, fps=60)
    assert world.start_pos is not None
    print(f"✓ World initialized with start position: {world.start_pos}")

    # Test physics integration
    robot.linear_vel = 1.0
    robot.update(0.1)
    print(f"✓ Physics update works: robot at ({robot.x:.2f}, {robot.y:.2f})")

    world.quit()
    print("\n✓ All initialization tests passed!")


if __name__ == "__main__":
    test_simulator_initialization()
