#!/usr/bin/env python3
"""
Mapper - Occupancy Grid Mapping (Rekonesans Stage 3)

Builds a real-time occupancy grid map by fusing:
- Robot position data from odometry (robot.pose)
- Obstacle data with distance from vision (vision.obstacle.data)

Architecture:
- Subscribes to robot.pose topic (from odometry)
- Subscribes to vision.obstacle.data topic (from vision with depth estimation)
- Maintains an in-memory occupancy grid (numpy array)
- Updates grid cells based on obstacle detections transformed to global coordinates
"""

from __future__ import annotations

import logging
import math
import os
import time

import numpy as np
import zmq

from common.bus import (
    TOPIC_MAPPER_MAP_DATA,
    TOPIC_NAVIGATOR_MAP_REQUEST,
    TOPIC_ROBOT_POSE,
    TOPIC_SLAM_MAP_STATE,
    TOPIC_VISION_OBSTACLE_DATA,
    BusPub,
    BusSub,
)

# Environment configuration
LOG_LEVEL = os.getenv("MAPPER_LOG_LEVEL", "INFO").upper()

# Map configuration
MAP_WIDTH_M = float(os.getenv("MAPPER_MAP_WIDTH_M", "10.0"))  # Map width in meters
MAP_HEIGHT_M = float(os.getenv("MAPPER_MAP_HEIGHT_M", "10.0"))  # Map height in meters
MAP_RESOLUTION_M = float(os.getenv("MAPPER_MAP_RESOLUTION_M", "0.05"))  # Cell size in meters (5cm)

# Initial robot position on the map (center of the map)
ROBOT_INIT_X = float(os.getenv("MAPPER_ROBOT_INIT_X", "0.0"))
ROBOT_INIT_Y = float(os.getenv("MAPPER_ROBOT_INIT_Y", "0.0"))

# Occupancy grid values
CELL_UNKNOWN = 127  # Unknown cell (gray)
CELL_FREE = 0  # Free space (white)
CELL_OCCUPIED = 255  # Occupied by obstacle (black)

# Update parameters
OBSTACLE_INFLATION_RADIUS = float(os.getenv("MAPPER_INFLATION_RADIUS", "0.1"))  # Inflate obstacles by this radius (m)

LOG = logging.getLogger("mapper")


class OccupancyGrid:
    """2D occupancy grid for SLAM mapping"""

    def __init__(self, width_m: float, height_m: float, resolution_m: float):
        """
        Initialize occupancy grid.

        Args:
            width_m: Map width in meters
            height_m: Map height in meters
            resolution_m: Cell size in meters
        """
        self.width_m = width_m
        self.height_m = height_m
        self.resolution_m = resolution_m

        # Calculate grid dimensions in cells
        self.width_cells = int(math.ceil(width_m / resolution_m))
        self.height_cells = int(math.ceil(height_m / resolution_m))

        # Initialize grid (all cells unknown)
        # Note: Grid uses (height, width) indexing following numpy convention: grid[row, col] = grid[y, x]
        self.grid = np.full((self.height_cells, self.width_cells), CELL_UNKNOWN, dtype=np.uint8)

        # Origin is at the center of the map
        self.origin_x = width_m / 2.0
        self.origin_y = height_m / 2.0

        LOG.info(
            f"Occupancy grid initialized: {self.width_cells}x{self.height_cells} cells, "
            f"resolution={resolution_m:.3f}m, size={width_m:.1f}x{height_m:.1f}m"
        )

    def world_to_grid(self, x: float, y: float) -> tuple[int, int]:
        """
        Convert world coordinates (meters) to grid coordinates (cells).

        Args:
            x: X coordinate in world frame (meters)
            y: Y coordinate in world frame (meters)

        Returns:
            Tuple of (grid_x, grid_y) in cells
        """
        # Transform from world coordinates (origin at center) to grid coordinates
        grid_x = int((x + self.origin_x) / self.resolution_m)
        grid_y = int((y + self.origin_y) / self.resolution_m)
        return grid_x, grid_y

    def is_valid_cell(self, grid_x: int, grid_y: int) -> bool:
        """Check if grid coordinates are within map bounds"""
        return 0 <= grid_x < self.width_cells and 0 <= grid_y < self.height_cells

    def set_occupied(self, grid_x: int, grid_y: int):
        """Mark a cell as occupied"""
        if self.is_valid_cell(grid_x, grid_y):
            self.grid[grid_y, grid_x] = CELL_OCCUPIED

    def set_free(self, grid_x: int, grid_y: int):
        """Mark a cell as free"""
        if self.is_valid_cell(grid_x, grid_y):
            self.grid[grid_y, grid_x] = CELL_FREE

    def mark_obstacle(self, x: float, y: float, inflation_radius: float = 0.0):
        """
        Mark an obstacle at world coordinates, optionally inflating it.

        Args:
            x: X coordinate in world frame (meters)
            y: Y coordinate in world frame (meters)
            inflation_radius: Radius to inflate obstacle (meters)
        """
        grid_x, grid_y = self.world_to_grid(x, y)

        if not self.is_valid_cell(grid_x, grid_y):
            LOG.debug(f"Obstacle at ({x:.2f}, {y:.2f}) is outside map bounds")
            return

        # Mark the obstacle cell
        self.set_occupied(grid_x, grid_y)

        # Inflate obstacle if requested
        if inflation_radius > 0:
            inflation_cells = int(math.ceil(inflation_radius / self.resolution_m))
            for dy in range(-inflation_cells, inflation_cells + 1):
                for dx in range(-inflation_cells, inflation_cells + 1):
                    # Only inflate within circular radius
                    if math.sqrt(dx**2 + dy**2) * self.resolution_m <= inflation_radius:
                        self.set_occupied(grid_x + dx, grid_y + dy)

    def get_occupancy_info(self) -> dict:
        """Get statistics about the occupancy grid"""
        total_cells = self.grid.size
        occupied_cells = np.sum(self.grid == CELL_OCCUPIED)
        free_cells = np.sum(self.grid == CELL_FREE)
        unknown_cells = np.sum(self.grid == CELL_UNKNOWN)

        return {
            "total_cells": int(total_cells),
            "occupied_cells": int(occupied_cells),
            "free_cells": int(free_cells),
            "unknown_cells": int(unknown_cells),
            "occupied_percent": float(occupied_cells / total_cells * 100.0),
            "explored_percent": float((occupied_cells + free_cells) / total_cells * 100.0),
        }


class Mapper:
    """SLAM Mapper - builds occupancy grid from robot pose and obstacle data"""

    def __init__(self):
        self.grid = OccupancyGrid(width_m=MAP_WIDTH_M, height_m=MAP_HEIGHT_M, resolution_m=MAP_RESOLUTION_M)

        # Bus connections
        self.sub_pose = BusSub(TOPIC_ROBOT_POSE)
        self.sub_obstacles = BusSub(TOPIC_VISION_OBSTACLE_DATA)
        self.sub_map_request = BusSub(TOPIC_NAVIGATOR_MAP_REQUEST)
        self.pub = BusPub()

        # Current robot pose
        self.robot_x = ROBOT_INIT_X
        self.robot_y = ROBOT_INIT_Y
        self.robot_theta = 0.0
        self.last_pose_ts = 0.0

        # Statistics
        self.obstacles_processed = 0
        self.last_stats_print_ts = time.time()
        self.last_map_state_ts = 0.0

        LOG.info(f"Mapper initialized at robot position ({self.robot_x:.2f}, {self.robot_y:.2f})")

    def _handle_robot_pose(self, payload: dict):
        """Update current robot pose from odometry"""
        self.robot_x = float(payload.get("x", 0.0))
        self.robot_y = float(payload.get("y", 0.0))
        self.robot_theta = float(payload.get("theta", 0.0))
        self.last_pose_ts = payload.get("ts", time.time())

        LOG.debug(
            f"Robot pose updated: ({self.robot_x:.3f}, {self.robot_y:.3f}, {math.degrees(self.robot_theta):.1f}°)"
        )
        self._publish_map_state(reason="pose")

    def _handle_obstacle_data(self, payload: dict):
        """
        Process obstacle data from vision.

        Expected payload format:
        {
            "obstacles": [
                {"angle": 0.0, "distance": 1.5},  # angle in radians, distance in meters
                ...
            ],
            "ts": 1234567890.123
        }
        """
        obstacles = payload.get("obstacles", [])

        if not obstacles:
            return

        # Transform each obstacle from robot local coordinates to global map coordinates
        valid_obstacles = 0
        for obs in obstacles:
            angle_local = float(obs.get("angle", 0.0))  # Angle relative to robot heading
            distance = float(obs.get("distance", 0.0))  # Distance in meters

            if distance <= 0:
                continue

            # Calculate obstacle position in global coordinates
            angle_global = self.robot_theta + angle_local

            # Obstacle position in global frame
            obs_x = self.robot_x + distance * math.cos(angle_global)
            obs_y = self.robot_y + distance * math.sin(angle_global)

            # Mark obstacle on the map
            self.grid.mark_obstacle(obs_x, obs_y, inflation_radius=OBSTACLE_INFLATION_RADIUS)

            LOG.debug(
                f"Obstacle: local_angle={math.degrees(angle_local):.1f}°, "
                f"dist={distance:.2f}m -> global=({obs_x:.2f}, {obs_y:.2f})"
            )

            valid_obstacles += 1

        self.obstacles_processed += valid_obstacles
        if valid_obstacles > 0:
            self._publish_map_state(reason="obstacle")

    def _handle_map_request(self, payload: dict):
        """
        Handle map data request from navigator.

        Publishes current occupancy grid data to the bus.
        """
        LOG.info("Received map request from navigator")

        # Prepare map data for transmission
        map_data = {
            "grid": self.grid.grid.tolist(),  # Convert numpy array to list for JSON serialization
            "width_cells": self.grid.width_cells,
            "height_cells": self.grid.height_cells,
            "resolution_m": self.grid.resolution_m,
            "origin_x": self.grid.origin_x,
            "origin_y": self.grid.origin_y,
            "width_m": self.grid.width_m,
            "height_m": self.grid.height_m,
            "ts": time.time(),
        }

        # Publish map data
        self.pub.publish(TOPIC_MAPPER_MAP_DATA, map_data, add_ts=True)
        LOG.info(f"Published map data: {self.grid.width_cells}x{self.grid.height_cells} cells")

    def _print_statistics(self):
        """Print mapping statistics periodically"""
        stats = self.grid.get_occupancy_info()
        LOG.info(
            f"Map stats: explored={stats['explored_percent']:.1f}%, "
            f"occupied={stats['occupied_percent']:.1f}%, "
            f"obstacles_processed={self.obstacles_processed}"
        )
        self._publish_map_state(reason="stats")

    def _publish_map_state(self, reason: str = "update") -> None:
        now = time.time()
        if reason == "pose" and (now - self.last_map_state_ts) < 1.0:
            return
        stats = self.grid.get_occupancy_info()
        payload = {
            "reason": reason,
            "ts": now,
            "pose": {"x": self.robot_x, "y": self.robot_y, "theta": self.robot_theta},
            "stats": stats,
        }
        self.pub.publish(TOPIC_SLAM_MAP_STATE, payload, add_ts=False)
        self.last_map_state_ts = now

    def run(self):
        """Main mapper loop"""
        LOG.info("Mapper main loop started")

        # Statistics print interval
        STATS_INTERVAL = 10.0  # seconds

        # Set up poller for efficient multi-socket polling
        poller = zmq.Poller()
        poller.register(self.sub_pose.sock, zmq.POLLIN)
        poller.register(self.sub_obstacles.sock, zmq.POLLIN)
        poller.register(self.sub_map_request.sock, zmq.POLLIN)

        try:
            while True:
                # Poll for messages with 10ms timeout
                socks = dict(poller.poll(timeout=10))

                # Check for robot pose updates
                if self.sub_pose.sock in socks:
                    topic, payload = self.sub_pose.recv(timeout_ms=0)
                    if topic and payload and topic == TOPIC_ROBOT_POSE:
                        self._handle_robot_pose(payload)

                # Check for obstacle data
                if self.sub_obstacles.sock in socks:
                    topic, payload = self.sub_obstacles.recv(timeout_ms=0)
                    if topic and payload and topic == TOPIC_VISION_OBSTACLE_DATA:
                        self._handle_obstacle_data(payload)

                # Check for map requests
                if self.sub_map_request.sock in socks:
                    topic, payload = self.sub_map_request.recv(timeout_ms=0)
                    if topic and payload and topic == TOPIC_NAVIGATOR_MAP_REQUEST:
                        self._handle_map_request(payload)

                # Print statistics periodically
                now = time.time()
                if now - self.last_stats_print_ts >= STATS_INTERVAL:
                    self._print_statistics()
                    self.last_stats_print_ts = now

                # Small sleep to prevent busy waiting
                time.sleep(0.01)

        except KeyboardInterrupt:
            LOG.info("Mapper interrupted by user")
        except Exception as e:
            LOG.exception(f"Error in mapper loop: {e}")
        finally:
            self.sub_pose.close()
            self.sub_obstacles.close()
            self.sub_map_request.close()
            self.pub.close()
            LOG.info("Mapper shutdown complete")
            self._print_statistics()  # Final statistics


def main():
    """Entry point"""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    mapper = Mapper()
    mapper.run()


if __name__ == "__main__":
    main()
