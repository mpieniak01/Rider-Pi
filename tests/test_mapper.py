#!/usr/bin/env python3
"""
Unit tests for Mapper module (Rekonesans Stage 3)
"""

import math
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from apps.mapper.main import CELL_OCCUPIED, CELL_UNKNOWN, Mapper, OccupancyGrid


class TestOccupancyGrid(unittest.TestCase):
    """Test OccupancyGrid functionality"""

    def setUp(self):
        """Set up test fixtures"""
        # Create a 10x10m grid with 0.1m resolution (100x100 cells)
        self.grid = OccupancyGrid(width_m=10.0, height_m=10.0, resolution_m=0.1)

    def test_initialization(self):
        """Test grid initializes correctly"""
        self.assertEqual(self.grid.width_m, 10.0)
        self.assertEqual(self.grid.height_m, 10.0)
        self.assertEqual(self.grid.resolution_m, 0.1)
        self.assertEqual(self.grid.width_cells, 100)
        self.assertEqual(self.grid.height_cells, 100)
        self.assertEqual(self.grid.origin_x, 5.0)  # Center of 10m map
        self.assertEqual(self.grid.origin_y, 5.0)

    def test_grid_all_unknown_initially(self):
        """Test all cells start as unknown"""
        self.assertTrue(np.all(self.grid.grid == CELL_UNKNOWN))

    def test_world_to_grid_center(self):
        """Test world to grid conversion at center (0,0)"""
        grid_x, grid_y = self.grid.world_to_grid(0.0, 0.0)
        # Center (0,0) in world should map to (50, 50) in grid
        self.assertEqual(grid_x, 50)
        self.assertEqual(grid_y, 50)

    def test_world_to_grid_positive(self):
        """Test world to grid conversion in positive quadrant"""
        # Point at (1.0, 1.0) in world
        grid_x, grid_y = self.grid.world_to_grid(1.0, 1.0)
        # origin is at 5.0, so (1.0 + 5.0) / 0.1 = 60
        self.assertEqual(grid_x, 60)
        self.assertEqual(grid_y, 60)

    def test_world_to_grid_negative(self):
        """Test world to grid conversion in negative quadrant"""
        # Point at (-1.0, -1.0) in world
        grid_x, grid_y = self.grid.world_to_grid(-1.0, -1.0)
        # origin is at 5.0, so (-1.0 + 5.0) / 0.1 = 40
        self.assertEqual(grid_x, 40)
        self.assertEqual(grid_y, 40)

    def test_is_valid_cell(self):
        """Test cell validity checking"""
        # Valid cells
        self.assertTrue(self.grid.is_valid_cell(0, 0))
        self.assertTrue(self.grid.is_valid_cell(50, 50))
        self.assertTrue(self.grid.is_valid_cell(99, 99))

        # Invalid cells (out of bounds)
        self.assertFalse(self.grid.is_valid_cell(-1, 50))
        self.assertFalse(self.grid.is_valid_cell(50, -1))
        self.assertFalse(self.grid.is_valid_cell(100, 50))
        self.assertFalse(self.grid.is_valid_cell(50, 100))

    def test_set_occupied(self):
        """Test marking cells as occupied"""
        self.grid.set_occupied(50, 50)
        self.assertEqual(self.grid.grid[50, 50], CELL_OCCUPIED)

    def test_mark_obstacle_at_origin(self):
        """Test marking obstacle at world origin (0, 0)"""
        self.grid.mark_obstacle(0.0, 0.0)
        grid_x, grid_y = self.grid.world_to_grid(0.0, 0.0)
        self.assertEqual(self.grid.grid[grid_y, grid_x], CELL_OCCUPIED)

    def test_mark_obstacle_with_inflation(self):
        """Test marking obstacle with inflation radius"""
        # Mark obstacle at origin with 0.2m inflation
        self.grid.mark_obstacle(0.0, 0.0, inflation_radius=0.2)

        grid_x, grid_y = self.grid.world_to_grid(0.0, 0.0)

        # Center cell should be occupied
        self.assertEqual(self.grid.grid[grid_y, grid_x], CELL_OCCUPIED)

        # Cells within inflation radius should be occupied
        # At 0.1m resolution, 0.2m inflation = 2 cells radius
        # Check adjacent cells
        self.assertEqual(self.grid.grid[grid_y + 1, grid_x], CELL_OCCUPIED)
        self.assertEqual(self.grid.grid[grid_y - 1, grid_x], CELL_OCCUPIED)
        self.assertEqual(self.grid.grid[grid_y, grid_x + 1], CELL_OCCUPIED)
        self.assertEqual(self.grid.grid[grid_y, grid_x - 1], CELL_OCCUPIED)

    def test_mark_obstacle_outside_map(self):
        """Test marking obstacle outside map bounds is handled gracefully"""
        # This should not crash or cause errors
        self.grid.mark_obstacle(100.0, 100.0)  # Way outside map
        # Grid should still be mostly unknown
        unknown_count = np.sum(self.grid.grid == CELL_UNKNOWN)
        self.assertEqual(unknown_count, 10000)  # All cells still unknown

    def test_get_occupancy_info(self):
        """Test getting occupancy statistics"""
        # Mark some obstacles
        self.grid.mark_obstacle(0.0, 0.0)
        self.grid.mark_obstacle(1.0, 0.0)
        self.grid.mark_obstacle(0.0, 1.0)

        info = self.grid.get_occupancy_info()

        self.assertEqual(info["total_cells"], 10000)
        self.assertEqual(info["occupied_cells"], 3)
        self.assertGreater(info["occupied_percent"], 0)
        self.assertGreater(info["explored_percent"], 0)


class TestMapper(unittest.TestCase):
    """Test Mapper system"""

    def setUp(self):
        """Set up test fixtures"""
        # Mock the bus connections
        self.bus_sub_patch = patch("apps.mapper.main.BusSub")

        self.mock_sub = self.bus_sub_patch.start()

        # Create mock instances
        self.mock_sub_pose = MagicMock()
        self.mock_sub_obstacles = MagicMock()

        # Return different instances for different topics
        def sub_side_effect(topic):
            if topic == "robot.pose":
                return self.mock_sub_pose
            elif topic == "vision.obstacle.data":
                return self.mock_sub_obstacles
            return MagicMock()

        self.mock_sub.side_effect = sub_side_effect

    def tearDown(self):
        """Clean up patches"""
        self.bus_sub_patch.stop()

    def test_mapper_initialization(self):
        """Test mapper initializes correctly"""
        mapper = Mapper()

        self.assertIsNotNone(mapper.grid)
        self.assertEqual(mapper.robot_x, 0.0)
        self.assertEqual(mapper.robot_y, 0.0)
        self.assertEqual(mapper.robot_theta, 0.0)
        self.assertEqual(mapper.obstacles_processed, 0)

    def test_handle_robot_pose(self):
        """Test handling robot pose updates"""
        mapper = Mapper()

        pose = {"x": 1.0, "y": 2.0, "theta": math.pi / 4, "ts": 1234567890.0}
        mapper._handle_robot_pose(pose)

        self.assertEqual(mapper.robot_x, 1.0)
        self.assertEqual(mapper.robot_y, 2.0)
        self.assertAlmostEqual(mapper.robot_theta, math.pi / 4)
        self.assertEqual(mapper.last_pose_ts, 1234567890.0)

    def test_handle_obstacle_data_single_obstacle(self):
        """Test handling obstacle data with single obstacle"""
        mapper = Mapper()

        # Robot at origin, facing east (0 radians)
        mapper.robot_x = 0.0
        mapper.robot_y = 0.0
        mapper.robot_theta = 0.0

        # Obstacle straight ahead at 2m
        obstacle_data = {
            "obstacles": [{"angle": 0.0, "distance": 2.0}],
            "ts": 1234567890.0,
        }

        mapper._handle_obstacle_data(obstacle_data)

        # Check that obstacle was marked
        self.assertEqual(mapper.obstacles_processed, 1)

        # Obstacle should be at (2.0, 0.0) in world coordinates
        grid_x, grid_y = mapper.grid.world_to_grid(2.0, 0.0)
        self.assertEqual(mapper.grid.grid[grid_y, grid_x], CELL_OCCUPIED)

    def test_handle_obstacle_data_robot_rotated(self):
        """Test obstacle handling with rotated robot"""
        mapper = Mapper()

        # Robot at origin, facing north (90 degrees = pi/2 radians)
        mapper.robot_x = 0.0
        mapper.robot_y = 0.0
        mapper.robot_theta = math.pi / 2

        # Obstacle straight ahead (relative to robot) at 2m
        obstacle_data = {
            "obstacles": [{"angle": 0.0, "distance": 2.0}],
            "ts": 1234567890.0,
        }

        mapper._handle_obstacle_data(obstacle_data)

        # Obstacle should be at approximately (0.0, 2.0) in world coordinates
        grid_x, grid_y = mapper.grid.world_to_grid(0.0, 2.0)

        # Check that cell is occupied (allowing for rounding)
        # The exact cell might vary slightly due to floating point, so check nearby cells too
        occupied_nearby = False
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if mapper.grid.is_valid_cell(grid_x + dx, grid_y + dy):
                    if mapper.grid.grid[grid_y + dy, grid_x + dx] == CELL_OCCUPIED:
                        occupied_nearby = True
                        break

        self.assertTrue(occupied_nearby, "No occupied cell found near expected obstacle location")

    def test_handle_obstacle_data_robot_translated(self):
        """Test obstacle handling with translated robot"""
        mapper = Mapper()

        # Robot at (1.0, 1.0), facing east
        mapper.robot_x = 1.0
        mapper.robot_y = 1.0
        mapper.robot_theta = 0.0

        # Obstacle straight ahead at 1m
        obstacle_data = {
            "obstacles": [{"angle": 0.0, "distance": 1.0}],
            "ts": 1234567890.0,
        }

        mapper._handle_obstacle_data(obstacle_data)

        # Obstacle should be at (2.0, 1.0) in world coordinates
        grid_x, grid_y = mapper.grid.world_to_grid(2.0, 1.0)
        self.assertEqual(mapper.grid.grid[grid_y, grid_x], CELL_OCCUPIED)

    def test_handle_obstacle_data_multiple_obstacles(self):
        """Test handling multiple obstacles at once"""
        mapper = Mapper()

        mapper.robot_x = 0.0
        mapper.robot_y = 0.0
        mapper.robot_theta = 0.0

        # Multiple obstacles
        obstacle_data = {
            "obstacles": [
                {"angle": 0.0, "distance": 2.0},  # Straight ahead
                {"angle": math.pi / 2, "distance": 1.5},  # To the left
                {"angle": -math.pi / 2, "distance": 1.5},  # To the right
            ],
            "ts": 1234567890.0,
        }

        mapper._handle_obstacle_data(obstacle_data)

        self.assertEqual(mapper.obstacles_processed, 3)

    def test_handle_obstacle_data_empty(self):
        """Test handling empty obstacle data"""
        mapper = Mapper()

        obstacle_data = {"obstacles": [], "ts": 1234567890.0}

        mapper._handle_obstacle_data(obstacle_data)

        self.assertEqual(mapper.obstacles_processed, 0)

    def test_handle_obstacle_data_invalid_distance(self):
        """Test handling obstacle with invalid distance"""
        mapper = Mapper()

        # Obstacle with zero or negative distance should be ignored
        obstacle_data = {
            "obstacles": [
                {"angle": 0.0, "distance": 0.0},
                {"angle": 0.0, "distance": -1.0},
            ],
            "ts": 1234567890.0,
        }

        mapper._handle_obstacle_data(obstacle_data)

        # No obstacles should be processed
        self.assertEqual(mapper.obstacles_processed, 0)

    def test_coordinate_transformation(self):
        """Test coordinate transformation from robot local to global frame"""
        mapper = Mapper()

        # Test case: Robot at (0, 0) rotated 90 degrees (facing north)
        # Obstacle 2m straight ahead should be at (0, 2)
        mapper.robot_x = 0.0
        mapper.robot_y = 0.0
        mapper.robot_theta = math.pi / 2

        obstacle_data = {
            "obstacles": [{"angle": 0.0, "distance": 2.0}],
            "ts": 1234567890.0,
        }

        mapper._handle_obstacle_data(obstacle_data)

        # Expected obstacle position in world: (0, 2)
        grid_x, grid_y = mapper.grid.world_to_grid(0.0, 2.0)

        # Check area around expected position (allowing for rounding)
        found_obstacle = False
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                test_x, test_y = grid_x + dx, grid_y + dy
                if mapper.grid.is_valid_cell(test_x, test_y):
                    if mapper.grid.grid[test_y, test_x] == CELL_OCCUPIED:
                        found_obstacle = True
                        break

        self.assertTrue(
            found_obstacle,
            "Obstacle not found at expected location after transformation",
        )


if __name__ == "__main__":
    unittest.main()
