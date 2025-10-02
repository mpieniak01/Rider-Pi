#!/usr/bin/env python3
"""
Rider-Pi 2D Simulator Entry Point
Launches the standalone 2D simulator for testing navigation algorithms.
Communicates with the motion control system via MQTT bus.
"""

from __future__ import annotations

import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sim.robot import SimulatedRobot
from sim.sensors import VirtualCamera, VirtualGyro
from sim.world import World

# Logging configuration
LOG_LEVEL = os.getenv("SIM_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

LOG = logging.getLogger("sim.main")

def main():
    """Main simulation loop."""
    # Determine map file
    map_file = os.getenv("SIM_MAP", "sim/maps/simple.txt")
    if not os.path.isabs(map_file):
        # Make relative to project root
        project_root = os.path.dirname(os.path.abspath(__file__))
        map_file = os.path.join(project_root, map_file)

    LOG.info("Starting Rider-Pi 2D Simulator")
    LOG.info(f"Map: {map_file}")

    # Initialize world
    world = World(map_file=map_file)

    # Initialize robot at start position
    if world.start_pos:
        rx, ry = world.start_pos
        robot = SimulatedRobot(x=rx + 0.5, y=ry + 0.5, angle=0.0)
    else:
        LOG.warning("No start position 'R' found in map, using (1, 1)")
        robot = SimulatedRobot(x=1.5, y=1.5, angle=0.0)

    # Initialize sensors
    gyro = VirtualGyro(rate_hz=10.0)
    camera = VirtualCamera(width=320, height=240, fov=60.0, rate_hz=5.0)

    LOG.info("Simulation started. Press ESC to quit.")

    # Main loop
    running = True
    try:
        while running:
            # Handle events
            running = world.handle_events()
            # Get delta time
            delta_time = world.tick()

            # Receive control commands
            robot.recv_commands()

            # Update robot physics
            robot.update(delta_time)

            # Publish sensor data
            gyro.publish(robot.angle)

            # Render camera view
            camera_surface = camera.render(robot.x, robot.y, robot.angle, world.wall_segments)
            camera.publish()

            # Render world
            world.render(robot, camera_surface)

    except KeyboardInterrupt:
        LOG.info("Simulation interrupted by user")
    except Exception as e:
        LOG.exception(f"Simulation error: {e}")
    finally:
        world.quit()
        LOG.info("Simulation stopped")

if __name__ == "__main__":
    main()
