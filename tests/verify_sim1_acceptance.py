#!/usr/bin/env python3
"""
Verification of SIM-1 Acceptance Criteria

This script verifies all acceptance criteria from the issue specification.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("\n" + "=" * 70)
print("SIM-1 ACCEPTANCE CRITERIA VERIFICATION")
print("=" * 70 + "\n")

criteria = []

# AC1: Uruchomienie run_simulation.py otwiera okno Pygame
print("[AC1] Run run_simulation.py opens Pygame window")
try:
    import pygame

    from sim.world import World

    os.environ["SDL_VIDEODRIVER"] = "dummy"
    world = World()

    assert world.screen is not None, "Pygame window should be created"
    assert world.width == 1280, "Window width should be 1280"
    assert world.height == 720, "Window height should be 720"

    world.quit()
    criteria.append(("AC1", True, "✓ Pygame window opens successfully"))
except Exception as e:
    criteria.append(("AC1", False, f"✗ Failed: {e}"))

# AC2: W oknie widoczny jest podział na panel mapy i panel boczny
print("\n[AC2] Window shows division between map panel and side panel")
try:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    world = World()

    # Check panel dimensions
    assert world.main_panel_width > 0, "Main panel should have width"
    assert world.side_panel_width > 0, "Side panel should have width"

    # Check ratio is approximately 70/30
    main_ratio = world.main_panel_width / world.width
    side_ratio = world.side_panel_width / world.width

    assert 0.65 < main_ratio < 0.75, f"Main panel should be ~70% (is {main_ratio:.1%})"
    assert 0.25 < side_ratio < 0.35, f"Side panel should be ~30% (is {side_ratio:.1%})"

    world.quit()
    criteria.append(("AC2", True, "✓ Window properly divided into map panel (~70%) and side panel (~30%)"))
except Exception as e:
    criteria.append(("AC2", False, f"✗ Failed: {e}"))

# AC3: Mapa zdefiniowana w pliku sim/maps/map01.txt jest poprawnie narysowana
print("\n[AC3] Map from sim/maps/map01.txt is correctly rendered")
try:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    world = World(map_file="sim/maps/map01.txt")

    # Check map loaded
    assert world.map_width > 0, "Map should have width"
    assert world.map_height > 0, "Map should have height"
    assert len(world.walls) > 0, "Map should have walls"

    # Check specific map01.txt details
    assert world.map_width == 15, "map01.txt width should be 15"
    assert world.map_height == 10, "map01.txt height should be 10"
    assert world.start_pos is not None, "Map should have start position 'R'"
    assert world.goal is not None, "Map should have goal 'M'"

    # Check rendering doesn't crash
    world.render()

    world.quit()
    criteria.append(("AC3", True, f"✓ Map rendered: {world.map_width}x{world.map_height}, {len(world.walls)} walls"))
except Exception as e:
    criteria.append(("AC3", False, f"✗ Failed: {e}"))

# AC4: Aplikację można zamknąć bez błędów
print("\n[AC4] Application can be closed without errors")
try:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    world = World(map_file="sim/maps/map01.txt")

    # Test event handling
    events_ok = world.handle_events()
    assert events_ok is True, "Event handling should work"

    # Test quit
    world.quit()

    criteria.append(("AC4", True, "✓ Application closes cleanly without errors"))
except Exception as e:
    criteria.append(("AC4", False, f"✗ Failed: {e}"))

# Print results
print("\n" + "=" * 70)
print("RESULTS")
print("=" * 70 + "\n")

passed = sum(1 for _, status, _ in criteria if status)
total = len(criteria)

for ac_id, _status, message in criteria:
    print(f"[{ac_id}] {message}")

print("\n" + "=" * 70)
print(f"SUMMARY: {passed}/{total} criteria passed")
print("=" * 70)

# Exit with appropriate code
sys.exit(0 if passed == total else 1)
