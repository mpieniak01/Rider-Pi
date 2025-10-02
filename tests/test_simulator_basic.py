#!/usr/bin/env python3
"""
Test basic simulator functionality for SIM-1
"""

from __future__ import annotations

import os
import tempfile

import pygame
import pytest


def test_world_initialization():
    """Test that World class can be initialized."""
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    from sim.world import World

    world = World()
    assert world.width > 0
    assert world.height > 0
    assert world.main_panel_width > 0
    assert world.side_panel_width > 0
    world.quit()


def test_map_loading_simple():
    """Test loading a simple map file."""
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    from sim.world import World

    world = World(map_file="sim/maps/simple.txt")
    assert world.map_width > 0, "Map width should be > 0"
    assert world.map_height > 0, "Map height should be > 0"
    assert len(world.walls) > 0, "Should have walls loaded"
    assert world.start_pos is not None, "Should have start position"
    assert world.goal is not None, "Should have goal position"
    world.quit()


def test_map_loading_map01():
    """Test loading map01.txt file."""
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    from sim.world import World

    world = World(map_file="sim/maps/map01.txt")
    assert world.map_width == 15
    assert world.map_height == 10
    assert len(world.walls) > 0
    assert world.start_pos == (7, 3), "Start position should be at (7, 3)"
    assert world.goal == (7, 7), "Goal should be at (7, 7)"
    world.quit()


def test_map_parsing():
    """Test that map characters are parsed correctly."""
    os.environ["SDL_VIDEODRIVER"] = "dummy"
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
        assert world.map_width == 5
        assert world.map_height == 5
        assert len(world.walls) == 16, "Should have 16 wall cells"
        assert world.start_pos == (2, 1), "Start should be at (2, 1)"
        assert world.goal == (2, 3), "Goal should be at (2, 3)"
        world.quit()
    finally:
        os.unlink(map_file)


def test_rendering():
    """Test that rendering works without errors."""
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    from sim.world import World

    world = World(map_file="sim/maps/simple.txt")
    # Should not raise any errors
    world.render()
    world.quit()


def test_panel_division():
    """Test that window is divided into panels correctly."""
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    from sim.world import World

    world = World()
    # Main panel should be ~70% of width
    expected_main = int(world.width * 0.7)
    assert abs(world.main_panel_width - expected_main) < 10
    # Side panel should be ~30% of width
    assert world.side_panel_width == world.width - world.main_panel_width
    world.quit()


def test_grid_to_screen_conversion():
    """Test coordinate conversion from grid to screen."""
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    from sim.world import World

    world = World(map_file="sim/maps/simple.txt")
    screen_x, screen_y = world.grid_to_screen(0, 0)
    # Should return valid screen coordinates
    assert screen_x >= 0
    assert screen_y >= 0
    world.quit()
