#!/usr/bin/env python3
"""SIM-1 acceptance checks; imports do not open a window or exit the process."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from acceptance_report import run_criteria, simulation_world


def check_window():
    """The dummy display retains the simulator's configured window dimensions."""
    with simulation_world() as world:
        assert world.screen is not None, "Pygame window should be created"
        assert world.width == 1280, "Window width should be 1280"
        assert world.height == 720, "Window height should be 720"
    return "✓ Pygame window opens successfully"


def check_panel_layout():
    """The map and side panels retain the expected nonempty 70/30 split."""
    with simulation_world() as world:
        assert world.main_panel_width > 0, "Main panel should have width"
        assert world.side_panel_width > 0, "Side panel should have width"
        main_ratio = world.main_panel_width / world.width
        side_ratio = world.side_panel_width / world.width
        assert 0.65 < main_ratio < 0.75, f"Main panel should be ~70% (is {main_ratio:.1%})"
        assert 0.25 < side_ratio < 0.35, f"Side panel should be ~30% (is {side_ratio:.1%})"
    return "✓ Window properly divided into map panel (~70%) and side panel (~30%)"


def check_map_rendering():
    """The SIM-1 map preserves dimensions, start, goal, walls and rendering."""
    with simulation_world(map_file="sim/maps/map01.txt") as world:
        assert world.map_width > 0, "Map should have width"
        assert world.map_height > 0, "Map should have height"
        assert len(world.walls) > 0, "Map should have walls"
        assert world.map_width == 15, "map01.txt width should be 15"
        assert world.map_height == 10, "map01.txt height should be 10"
        assert world.start_pos is not None, "Map should have start position 'R'"
        assert world.goal is not None, "Map should have goal 'M'"
        world.render()
        message = f"✓ Map rendered: {world.map_width}x{world.map_height}, {len(world.walls)} walls"
    return message


def check_window_shutdown():
    """Event handling succeeds and the context closes the simulator window."""
    with simulation_world(map_file="sim/maps/map01.txt") as world:
        assert world.handle_events() is True, "Event handling should work"
    return "✓ Application closes cleanly without errors"


def main():
    """Run all four original SIM-1 checks with a nonzero failure status."""
    criteria = [
        ("AC1", "Run scripts/sim/run_simulation.py opens Pygame window", check_window),
        ("AC2", "Window shows division between map panel and side panel", check_panel_layout),
        ("AC3", "Map from sim/maps/map01.txt is correctly rendered", check_map_rendering),
        ("AC4", "Application can be closed without errors", check_window_shutdown),
    ]
    return run_criteria("SIM-1 ACCEPTANCE CRITERIA VERIFICATION", criteria)


if __name__ == "__main__":
    sys.exit(main())
