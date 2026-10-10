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
from common.data_quality import finite_number, frame_identity, pose_status, sample_status

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
MAX_MAP_CELLS = 65536
MAX_MAP_AGE_S = 3.0


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
        if not all(finite_number(value) and value > 0 for value in (width_m, height_m, resolution_m)):
            raise ValueError("invalid_grid_geometry")
        dimensions = (width_m / resolution_m, height_m / resolution_m)
        if not all(finite_number(value) for value in dimensions):
            raise ValueError("grid_too_large")
        width, height = (math.ceil(value) for value in dimensions)
        if width * height > MAX_MAP_CELLS:
            raise ValueError("grid_too_large")
        self.width_m = width_m
        self.height_m = height_m
        self.resolution_m = resolution_m

        # Calculate grid dimensions in cells
        self.width_cells = int(math.ceil(width_m / resolution_m))
        self.height_cells = int(math.ceil(height_m / resolution_m))

        # Initialize grid (all cells unknown)
        # Note: Grid uses (height, width) indexing following numpy convention: grid[row, col] = grid[y, x]
        self.grid = np.full((self.height_cells, self.width_cells), CELL_UNKNOWN, dtype=np.uint8)
        self.observed = np.zeros((self.height_cells, self.width_cells), dtype=float)
        self.observation_time = None

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
        grid_x = math.floor((x + self.origin_x) / self.resolution_m)
        grid_y = math.floor((y + self.origin_y) / self.resolution_m)
        return grid_x, grid_y

    def is_valid_cell(self, grid_x: int, grid_y: int) -> bool:
        """Check if grid coordinates are within map bounds"""
        return 0 <= grid_x < self.width_cells and 0 <= grid_y < self.height_cells

    def set_occupied(self, grid_x: int, grid_y: int):
        """Mark a cell as occupied"""
        if self.is_valid_cell(grid_x, grid_y):
            self.grid[grid_y, grid_x] = CELL_OCCUPIED
            self.observed[grid_y, grid_x] = self.observation_time or 0.0

    def set_free(self, grid_x: int, grid_y: int):
        """Mark a cell as free"""
        if self.is_valid_cell(grid_x, grid_y):
            # A ray never clears a newer occupied cell.
            if self.grid[grid_y, grid_x] != CELL_OCCUPIED:
                self.grid[grid_y, grid_x] = CELL_FREE
                self.observed[grid_y, grid_x] = self.observation_time or 0.0

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        result = self.grid.copy()
        result[(now - self.observed > MAX_MAP_AGE_S) | (self.observed <= 0) | (self.observed > now + 0.1)] = (
            CELL_UNKNOWN
        )
        return result.tolist()

    def mark_ray(self, start_x, start_y, end_x, end_y):
        x0, y0 = self.world_to_grid(start_x, start_y)
        x1, y1 = self.world_to_grid(end_x, end_y)
        steps = max(abs(x1 - x0), abs(y1 - y0))
        if steps > MAX_MAP_CELLS or not steps:
            return
        for index in range(steps):
            fraction = index / steps
            self.set_free(round(x0 + (x1 - x0) * fraction), round(y0 + (y1 - y0) * fraction))

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

    def get_occupancy_info(self, now=None) -> dict:
        """Get statistics about the occupancy grid"""
        grid = self.grid if now is None else np.asarray(self.snapshot(now), dtype=np.uint8)
        total_cells = grid.size
        occupied_cells = np.sum(grid == CELL_OCCUPIED)
        free_cells = np.sum(grid == CELL_FREE)
        unknown_cells = np.sum(grid == CELL_UNKNOWN)

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

    def __init__(self, *, wall_clock=time.time):
        self.wall_clock = wall_clock
        self.grid = OccupancyGrid(width_m=MAP_WIDTH_M, height_m=MAP_HEIGHT_M, resolution_m=MAP_RESOLUTION_M)

        # Bus connections
        self.sub_pose = BusSub(TOPIC_ROBOT_POSE)
        self.sub_obstacles = BusSub(TOPIC_VISION_OBSTACLE_DATA)
        self.sub_map_request = BusSub(TOPIC_NAVIGATOR_MAP_REQUEST)
        self.pub = BusPub()

        # Current robot pose
        self.robot_x = self.robot_y = self.robot_theta = None
        self.last_pose_ts = 0.0
        self.pose_sample = self.range_sample = None
        self.frame = None
        self.data_error = "inputs_pending"
        self.last_range_ts = None

        # Statistics
        self.obstacles_processed = 0
        self.last_stats_print_ts = self.wall_clock()
        self.last_map_state_ts = 0.0

        LOG.info("Mapper initialized with unknown physical pose")

    def _handle_robot_pose(self, payload: dict):
        """Update current robot pose from odometry"""
        # A replacement calibration invalidates old cells even before a new
        # manual reference exists. Publication time is used only to discard
        # history, never to claim a fresh physical pose or map observation.
        revision = payload.get("calibration_id") if isinstance(payload, dict) else None
        published = payload.get("ts") if isinstance(payload, dict) else None
        if (
            self.frame is not None
            and isinstance(revision, str)
            and revision
            and revision != self.frame[0]
            and finite_number(published)
            and 0 <= self.wall_clock() - published <= 3.0
        ):
            self.grid.grid.fill(CELL_UNKNOWN)
            self.grid.observed.fill(0.0)
            self.grid.observation_time = None
            self.range_sample = None
            self.last_range_ts = None
            self.frame = None
            self.robot_x = self.robot_y = self.robot_theta = None
        quality = pose_status(payload, previous_ts=self.last_pose_ts, now=self.wall_clock())
        if not quality["ready"]:
            self.pose_sample = None
            self.data_error = quality["error"]
            self._publish_map_state(reason="pose")
            return
        identity = frame_identity(payload)
        if self.frame != identity:
            self.grid.grid.fill(CELL_UNKNOWN)
            self.grid.observed.fill(0.0)
            self.grid.observation_time = None
            self.range_sample = None
            self.last_range_ts = None
            self.data_error = "new_frame_range_pending"
            self.frame = identity
        self.robot_x, self.robot_y, self.robot_theta = (payload[key] for key in ("x", "y", "theta"))
        self.last_pose_ts = quality["observed_at"]
        self.pose_sample = dict(payload)

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
        quality = sample_status(payload, max_age_s=0.5, previous_ts=self.last_range_ts, now=self.wall_clock())
        pose = pose_status(self.pose_sample, now=self.wall_clock())
        if not quality["ready"] or not pose["ready"]:
            self.range_sample = None
            self.data_error = quality["error"] or pose["error"]
            self._publish_map_state(reason="range")
            return
        if (
            payload.get("range_verified") is not True
            or not isinstance(payload.get("calibration_id"), str)
            or not payload["calibration_id"]
        ):
            self.range_sample = None
            self.data_error = "range_manual_characterization_required"
            return
        radius = payload.get("footprint_radius_m")
        if (
            payload.get("traversability_verified") is not True
            or payload.get("footprint_verified") is not True
            or payload.get("stopping_horizon_verified") is not True
            or not finite_number(payload.get("stopping_horizon_m"))
            or payload["stopping_horizon_m"] <= 0
            or not finite_number(radius)
            or not 0 < radius <= min(self.grid.width_m, self.grid.height_m)
        ):
            self.range_sample = None
            self.data_error = "footprint_range_and_stopping_horizon_unverified"
            return
        obstacles = payload.get("obstacles")
        if not isinstance(obstacles, list) or not 0 < len(obstacles) <= 128:
            self.range_sample = None
            self.data_error = "range_geometry_unknown"
            return
        for obs in obstacles:
            if (
                not isinstance(obs, dict)
                or not all(finite_number(obs.get(key)) for key in ("angle", "distance"))
                or obs["distance"] <= 0
            ):
                self.range_sample = None
                self.data_error = "invalid_range_geometry"
                return
        # Conservatively bound source synchronization to the same data budget.
        if abs(quality["observed_at"] - pose["observed_at"]) > 0.5:
            self.range_sample = None
            self.data_error = "pose_range_unsynchronized"
            return
        self.range_sample = dict(payload)
        self.last_range_ts = quality["observed_at"]
        self.grid.observation_time = min(quality["observed_at"], pose["observed_at"])
        self.data_error = None

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
            self.grid.mark_ray(self.robot_x, self.robot_y, obs_x, obs_y)
            self.grid.mark_obstacle(obs_x, obs_y, inflation_radius=radius)

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
            "grid": self.grid.snapshot(self.wall_clock()),
            "width_cells": self.grid.width_cells,
            "height_cells": self.grid.height_cells,
            "resolution_m": self.grid.resolution_m,
            "origin_x": self.grid.origin_x,
            "origin_y": self.grid.origin_y,
            "width_m": self.grid.width_m,
            "height_m": self.grid.height_m,
            "ts": self.wall_clock(),
            "request_id": payload.get("request_id"),
            **self.quality(),
        }

        # Publish map data
        self.pub.publish(TOPIC_MAPPER_MAP_DATA, map_data, add_ts=True)
        LOG.info(f"Published map data: {self.grid.width_cells}x{self.grid.height_cells} cells")

    def _print_statistics(self):
        """Print mapping statistics periodically"""
        stats = self.grid.get_occupancy_info(self.wall_clock())
        LOG.info(
            f"Map stats: explored={stats['explored_percent']:.1f}%, "
            f"occupied={stats['occupied_percent']:.1f}%, "
            f"obstacles_processed={self.obstacles_processed}"
        )
        self._publish_map_state(reason="stats")

    def quality(self):
        pose = pose_status(self.pose_sample, now=self.wall_clock())
        ranges = sample_status(self.range_sample, max_age_s=0.5, now=self.wall_clock())
        error = self.data_error or pose["error"] or ranges["error"]
        observed = min(pose["observed_at"], ranges["observed_at"]) if pose["ready"] and ranges["ready"] else None
        return {
            "data_ready": error is None,
            "planning_ready": error is None,
            "navigation_ready": False,
            "navigation_error": "navigation_traversal_unverified",
            "error": error,
            "observed_at": observed,
            "pose_quality": pose,
            "range_quality": ranges,
            "calibration_id": self.frame[0] if self.frame else None,
            "reference_id": self.frame[1] if self.frame else None,
            "home": self.pose_sample.get("home") if self.pose_sample else None,
            "range_calibration_id": self.range_sample.get("calibration_id") if self.range_sample else None,
            "stopping_horizon_verified": self.range_sample.get("stopping_horizon_verified")
            if self.range_sample
            else False,
            "stopping_horizon_m": self.range_sample.get("stopping_horizon_m") if self.range_sample else None,
            "physical_completion": "unverified",
        }

    def _publish_map_state(self, reason: str = "update") -> None:
        now = self.wall_clock()
        if reason == "pose" and (now - self.last_map_state_ts) < 1.0:
            return
        stats = self.grid.get_occupancy_info(now)
        payload = {
            "reason": reason,
            "ts": now,
            "pose": {"x": self.robot_x, "y": self.robot_y, "theta": self.robot_theta},
            "stats": stats,
            **self.quality(),
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
                now = self.wall_clock()
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
