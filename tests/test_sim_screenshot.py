#!/usr/bin/env python3
"""
Create a screenshot of the basic simulator to demonstrate functionality
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up SDL for offscreen rendering
os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame

from sim.world import World

print("Creating simulator screenshot for SIM-1...")

# Initialize world with map01
world = World(map_file="sim/maps/map01.txt")

# Render a frame
import pygame


class _DummyRobot:
    def __init__(self, x=0.0, y=0.0, angle=0.0):
        self.x = float(x)
        self.y = float(y)
        self.angle = float(angle)
        self.linear_vel = 0.0
        self.angular_vel = 0.0

    def get_state(self):
        return {
            "x": self.x,
            "y": self.y,
            "angle": self.angle,
            "linear_vel": self.linear_vel,
            "angular_vel": self.angular_vel,
        }


dummy_robot = _DummyRobot(0.0, 0.0, 0.0)
camera_surface = getattr(world, "camera_surface", None) or pygame.Surface((1280, 720))
world.render(dummy_robot, camera_surface)

# Save screenshot
pygame.image.save(world.screen, "sim_basic_screenshot.png")
print("✓ Screenshot saved to sim_basic_screenshot.png")

# Show some stats
print("\nSimulator Stats:")
print(f"  Window size: {world.width}x{world.height}")
print(f"  Main panel: {world.main_panel_width}px")
print(f"  Side panel: {world.side_panel_width}px")
print(f"  Map size: {world.map_width}x{world.map_height}")
print(f"  Walls: {len(world.walls)}")
print(f"  Start position: {world.start_pos}")
print(f"  Goal position: {world.goal}")

world.quit()
