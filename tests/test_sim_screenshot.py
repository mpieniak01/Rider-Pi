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
world.render()

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
