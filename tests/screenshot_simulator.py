#!/usr/bin/env python3
"""
Create a screenshot of the simulator for documentation
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up SDL for offscreen rendering
os.environ["SDL_VIDEODRIVER"] = "dummy"

from sim.robot import SimulatedRobot
from sim.sensors import VirtualCamera
from sim.world import World

print("Creating simulator screenshot...")

# Initialize world with simple map
world = World(map_file="sim/maps/simple.txt")

# Initialize robot
if world.start_pos:
    rx, ry = world.start_pos
    robot = SimulatedRobot(x=rx + 0.5, y=ry + 0.5, angle=0.0)
else:
    robot = SimulatedRobot(x=5.5, y=4.5, angle=0.0)

# Position robot at interesting angle and location
robot.x = 8.0
robot.y = 5.0
robot.angle = 0.5  # About 30 degrees

# Create camera
camera = VirtualCamera(width=320, height=240)

# Render a few frames to let things settle
for _i in range(5):
    robot.update(0.016)
    camera_surface = camera.render(robot.x, robot.y, robot.angle, world.wall_segments)
    world.render(robot, camera_surface)
    world.tick()

# Save screenshot
import pygame

pygame.image.save(world.screen, "sim_screenshot.png")
print("✓ Screenshot saved to sim_screenshot.png")

world.quit()
