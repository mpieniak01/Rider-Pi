#!/usr/bin/env python3
"""
Unit tests for Navigator pathfinding module (Rekonesans Stage 4)
"""

import unittest

import numpy as np

from apps.navigator.pathfinding import (
    CELL_FREE,
    CELL_OCCUPIED,
    CELL_UNKNOWN,
    find_path,
    find_path_grid,
    grid_to_world,
    simplify_path,
    world_to_grid,
)


class TestPathfinding(unittest.TestCase):
    """Test pathfinding algorithms"""

    def test_world_to_grid_conversion(self):
        """Test converting world coordinates to grid coordinates"""
        resolution = 0.05  # 5cm per cell
        origin_x = 5.0  # Map origin at (5, 5) in world coordinates
        origin_y = 5.0

        # Point at world origin (0, 0) should be at grid center
        gx, gy = world_to_grid(0.0, 0.0, resolution, origin_x, origin_y)
        self.assertEqual(gx, 100)  # (0 + 5.0) / 0.05 = 100
        self.assertEqual(gy, 100)

        # Point at (1, 1) in world
        gx, gy = world_to_grid(1.0, 1.0, resolution, origin_x, origin_y)
        self.assertEqual(gx, 120)  # (1 + 5.0) / 0.05 = 120
        self.assertEqual(gy, 120)

    def test_grid_to_world_conversion(self):
        """Test converting grid coordinates to world coordinates"""
        resolution = 0.05
        origin_x = 5.0
        origin_y = 5.0

        # Grid (100, 100) should be at world origin
        wx, wy = grid_to_world(100, 100, resolution, origin_x, origin_y)
        self.assertAlmostEqual(wx, 0.0, places=5)
        self.assertAlmostEqual(wy, 0.0, places=5)

        # Grid (120, 120) should be at (1, 1)
        wx, wy = grid_to_world(120, 120, resolution, origin_x, origin_y)
        self.assertAlmostEqual(wx, 1.0, places=5)
        self.assertAlmostEqual(wy, 1.0, places=5)

    def test_simple_path_no_obstacles(self):
        """Test pathfinding on simple grid with no obstacles"""
        # Create 10x10 grid, all free
        grid = np.full((10, 10), CELL_FREE, dtype=np.uint8)

        # Find path from (0, 0) to (9, 9)
        path = find_path_grid(grid, 0, 0, 9, 9, 10, 10)

        self.assertIsNotNone(path)
        self.assertGreater(len(path), 0)
        self.assertEqual(path[0], (0, 0))  # Start
        self.assertEqual(path[-1], (9, 9))  # Goal

    def test_path_with_obstacle(self):
        """Test pathfinding with obstacle in the way"""
        # Create 10x10 grid
        grid = np.full((10, 10), CELL_FREE, dtype=np.uint8)

        # Add vertical wall from (5, 0) to (5, 7)
        for y in range(8):
            grid[y, 5] = CELL_OCCUPIED

        # Find path from (0, 5) to (9, 5) - must go around wall
        path = find_path_grid(grid, 0, 5, 9, 5, 10, 10)

        self.assertIsNotNone(path)
        self.assertEqual(path[0], (0, 5))
        self.assertEqual(path[-1], (9, 5))

        # Path should not go through the wall at x=5, y<8
        for x, y in path:
            if y < 8:  # Only check wall region
                self.assertNotEqual(x, 5, f"Path goes through wall at ({x}, {y})")

    def test_no_path_blocked(self):
        """Test pathfinding when goal is completely blocked"""
        # Create 10x10 grid
        grid = np.full((10, 10), CELL_FREE, dtype=np.uint8)

        # Surround goal (9, 9) with obstacles
        for x in range(8, 10):
            for y in range(8, 10):
                if (x, y) != (9, 9):
                    grid[y, x] = CELL_OCCUPIED

        # Block the only approach
        grid[7, 9] = CELL_OCCUPIED
        grid[9, 7] = CELL_OCCUPIED

        # No path should exist
        path = find_path_grid(grid, 0, 0, 9, 9, 10, 10)
        self.assertIsNone(path)

    def test_simplify_path_straight_line(self):
        """Test path simplification for straight line"""
        # Path going straight from (0,0) to (5,0)
        path = [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0)]
        simplified = simplify_path(path)

        # Should be simplified to just start and end
        self.assertEqual(len(simplified), 2)
        self.assertEqual(simplified[0], (0, 0))
        self.assertEqual(simplified[-1], (5, 0))

    def test_simplify_path_with_turn(self):
        """Test path simplification with a turn"""
        # Path with a 90-degree turn
        path = [(0, 0), (1, 0), (2, 0), (2, 1), (2, 2), (2, 3)]
        simplified = simplify_path(path)

        # Should keep the turn point
        self.assertGreaterEqual(len(simplified), 3)
        self.assertEqual(simplified[0], (0, 0))
        self.assertEqual(simplified[-1], (2, 3))
        # Turn point should be in the simplified path
        self.assertIn((2, 0), simplified)

    def test_find_path_integration(self):
        """Test full pathfinding with world coordinates"""
        # Create 20x20 grid (10m x 10m at 0.5m resolution)
        width_cells = 20
        height_cells = 20
        resolution = 0.5
        origin_x = 5.0
        origin_y = 5.0

        grid = np.full((height_cells, width_cells), CELL_FREE, dtype=np.uint8)

        # Add obstacle
        grid[10, 10] = CELL_OCCUPIED

        grid_data = {
            "grid": grid.tolist(),
            "width_cells": width_cells,
            "height_cells": height_cells,
            "resolution_m": resolution,
            "origin_x": origin_x,
            "origin_y": origin_y,
        }

        # Find path from (-2, -2) to (2, 2) in world coordinates
        start_pose = (-2.0, -2.0)
        goal_pose = (2.0, 2.0)

        path = find_path(grid_data, start_pose, goal_pose)

        self.assertIsNotNone(path)
        self.assertGreater(len(path), 0)

        # First waypoint should be close to start
        self.assertAlmostEqual(path[0][0], start_pose[0], delta=resolution)
        self.assertAlmostEqual(path[0][1], start_pose[1], delta=resolution)

        # Last waypoint should be close to goal
        self.assertAlmostEqual(path[-1][0], goal_pose[0], delta=resolution)
        self.assertAlmostEqual(path[-1][1], goal_pose[1], delta=resolution)

    def test_unknown_cells_allowed(self):
        """Test pathfinding allows traversing unknown cells when configured"""
        grid = np.full((10, 10), CELL_UNKNOWN, dtype=np.uint8)

        # Set start and goal as free
        grid[0, 0] = CELL_FREE
        grid[9, 9] = CELL_FREE

        # Should find path through unknown cells
        path = find_path_grid(grid, 0, 0, 9, 9, 10, 10, allow_unknown=True)
        self.assertIsNotNone(path)

    def test_unknown_cells_blocked(self):
        """Test pathfinding avoids unknown cells when configured"""
        grid = np.full((10, 10), CELL_UNKNOWN, dtype=np.uint8)

        # Clear a path
        for i in range(10):
            grid[i, 0] = CELL_FREE
            grid[9, i] = CELL_FREE

        grid[0, 0] = CELL_FREE
        grid[9, 9] = CELL_FREE

        # Should find path only through free cells
        path = find_path_grid(grid, 0, 0, 9, 9, 10, 10, allow_unknown=False)
        self.assertIsNotNone(path)

        # All cells in path should be free
        for x, y in path:
            self.assertEqual(grid[y, x], CELL_FREE)


if __name__ == "__main__":
    unittest.main()
