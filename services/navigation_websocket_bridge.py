#!/usr/bin/env python3
"""
Navigation WebSocket Bridge - Real-time navigation data streaming

Subscribes to navigation-related bus topics and forwards data to WebSocket clients.
Provides real-time visualization data for the /navigation.html panel.

Topics subscribed:
- robot.pose (from odometry): Robot position and orientation
- mapper.map.data (from mapper): Occupancy grid map data
- navigator.* (from navigator): Path planning and navigation state

WebSocket endpoint: /ws/navigation
Message format: JSON with 'type' field indicating data type
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

try:
    from flask_sock import Sock
except ImportError:
    Sock = None  # type: ignore

from common.bus import (
    TOPIC_MAPPER_MAP_DATA,
    TOPIC_ROBOT_POSE,
    BusSub,
)

LOG_LEVEL = os.getenv("NAV_WS_LOG_LEVEL", "INFO").upper()
LOG = logging.getLogger("nav_ws_bridge")

# Grid cell value constants (from mapper)
MAPPER_CELL_OCCUPIED = 255  # Obstacle
MAPPER_CELL_FREE = 0  # Free space
MAPPER_CELL_UNKNOWN = 127  # Unknown/unexplored

# Frontend grid cell values
FRONTEND_CELL_OBSTACLE = 1
FRONTEND_CELL_FREE = 2
FRONTEND_CELL_UNKNOWN = -1


class NavigationWebSocketBridge:
    """
    Bridge between ZMQ bus topics and WebSocket clients.
    Subscribes to navigation data and broadcasts to all connected WebSocket clients.
    """

    def __init__(self):
        self.clients: set = set()
        self.lock = threading.Lock()
        self.running = False
        self.bus_thread: threading.Thread | None = None

        # Bus subscribers
        self.sub_pose: BusSub | None = None
        self.sub_map: BusSub | None = None

        # Last known data for new clients
        self.last_pose: dict[str, Any] | None = None
        self.last_map: dict[str, Any] | None = None

        LOG.info("NavigationWebSocketBridge initialized")

    def start(self) -> None:
        """Start the background thread that reads from bus and broadcasts to clients"""
        if self.running:
            LOG.warning("Bridge already running")
            return

        self.running = True

        # Initialize bus subscribers
        self.sub_pose = BusSub(TOPIC_ROBOT_POSE)
        self.sub_map = BusSub(TOPIC_MAPPER_MAP_DATA)

        # Start background thread
        self.bus_thread = threading.Thread(target=self._bus_loop, daemon=True)
        self.bus_thread.start()

        LOG.info("NavigationWebSocketBridge started")

    def stop(self) -> None:
        """Stop the background thread and close bus connections"""
        self.running = False

        if self.bus_thread:
            self.bus_thread.join(timeout=2.0)

        if self.sub_pose:
            self.sub_pose.close()
        if self.sub_map:
            self.sub_map.close()

        LOG.info("NavigationWebSocketBridge stopped")

    def add_client(self, ws) -> None:
        """Register a new WebSocket client"""
        with self.lock:
            self.clients.add(ws)
            LOG.info(f"Client connected. Total clients: {len(self.clients)}")

            # Send last known data to new client
            if self.last_pose:
                self._send_to_client(ws, {"type": "odometry", "data": self.last_pose})
            if self.last_map:
                self._send_to_client(ws, {"type": "map", "data": self.last_map})

    def remove_client(self, ws) -> None:
        """Unregister a WebSocket client"""
        with self.lock:
            self.clients.discard(ws)
            LOG.info(f"Client disconnected. Total clients: {len(self.clients)}")

    def _send_to_client(self, ws, message: dict) -> None:
        """Send a message to a specific client"""
        try:
            ws.send(json.dumps(message, ensure_ascii=False))
        except Exception as e:
            LOG.debug(f"Failed to send to client: {e}")

    def _broadcast(self, message: dict) -> None:
        """Broadcast a message to all connected clients"""
        with self.lock:
            dead_clients = set()
            for ws in self.clients:
                try:
                    ws.send(json.dumps(message, ensure_ascii=False))
                except Exception as e:
                    LOG.debug(f"Failed to send to client, marking for removal: {e}")
                    dead_clients.add(ws)

            # Remove dead clients
            for ws in dead_clients:
                self.clients.discard(ws)

    def _bus_loop(self) -> None:
        """Background thread that reads from bus and broadcasts to WebSocket clients"""
        LOG.info("Bus loop started")

        try:
            while self.running:
                # Check for robot pose updates
                if self.sub_pose:
                    topic, payload = self.sub_pose.recv(timeout_ms=10)
                    if topic and payload and topic == TOPIC_ROBOT_POSE:
                        self._handle_pose(payload)

                # Check for map updates
                if self.sub_map:
                    topic, payload = self.sub_map.recv(timeout_ms=10)
                    if topic and payload and topic == TOPIC_MAPPER_MAP_DATA:
                        self._handle_map(payload)

                # Small sleep to prevent busy waiting
                time.sleep(0.01)

        except Exception as e:
            LOG.exception(f"Error in bus loop: {e}")
        finally:
            LOG.info("Bus loop stopped")

    def _handle_pose(self, payload: dict) -> None:
        """Handle robot pose update from odometry"""
        # Transform pose data for frontend
        # Frontend expects: { x, y, angle }
        # Odometry provides: { x, y, theta, theta_deg, ts }
        x = payload.get("x", 0.0)
        y = payload.get("y", 0.0)
        theta = payload.get("theta", 0.0)

        # Convert world coordinates to grid coordinates (simplified)
        # In real implementation, this should use the map origin and resolution
        # For now, we'll just pass through the coordinates
        frontend_data = {
            "x": float(x),
            "y": float(y),
            "angle": float(theta),
        }

        self.last_pose = frontend_data

        message = {"type": "odometry", "data": frontend_data}
        self._broadcast(message)

        LOG.debug(f"Broadcast pose: x={x:.3f}, y={y:.3f}, theta={theta:.3f}")

    def _handle_map(self, payload: dict) -> None:
        """Handle map data update from mapper"""
        # Transform map data for frontend
        # Frontend expects: { width, height, data, origin }
        # Mapper provides: { grid, width_cells, height_cells, resolution_m, origin_x, origin_y, ... }

        # Extract map data
        grid = payload.get("grid", [])
        width_cells = payload.get("width_cells", 0)
        height_cells = payload.get("height_cells", 0)
        resolution_m = payload.get("resolution_m", 0.05)
        origin_x = payload.get("origin_x", 0.0)
        origin_y = payload.get("origin_y", 0.0)

        # Validate resolution
        if resolution_m <= 0:
            LOG.warning(f"Invalid resolution_m={resolution_m}, using default 0.05")
            resolution_m = 0.05

        # Flatten grid if it's 2D array
        if isinstance(grid, list) and grid and isinstance(grid[0], list):
            flat_grid = []
            for row in grid:
                flat_grid.extend(row)
        else:
            flat_grid = grid

        # Convert occupancy values (mapper → frontend format)
        frontend_grid = []
        for cell in flat_grid:
            if cell == MAPPER_CELL_OCCUPIED:
                frontend_grid.append(FRONTEND_CELL_OBSTACLE)
            elif cell == MAPPER_CELL_FREE:
                frontend_grid.append(FRONTEND_CELL_FREE)
            else:  # MAPPER_CELL_UNKNOWN or other
                frontend_grid.append(FRONTEND_CELL_UNKNOWN)

        frontend_data = {
            "width": width_cells,
            "height": height_cells,
            "data": frontend_grid,
            "origin": {"x": origin_x / resolution_m, "y": origin_y / resolution_m},
        }

        self.last_map = frontend_data

        message = {"type": "map", "data": frontend_data}
        self._broadcast(message)

        LOG.debug(f"Broadcast map: {width_cells}x{height_cells} cells, {len(frontend_grid)} values")


# Global bridge instance
_bridge: NavigationWebSocketBridge | None = None


def get_bridge() -> NavigationWebSocketBridge:
    """Get or create the global bridge instance"""
    global _bridge
    if _bridge is None:
        _bridge = NavigationWebSocketBridge()
    return _bridge


def register_websocket_endpoint(app) -> None:
    """
    Register the /ws/navigation WebSocket endpoint with the Flask app.

    Args:
        app: Flask application instance
    """
    if Sock is None:
        LOG.error("flask-sock not available. WebSocket endpoint not registered.")
        return

    sock = Sock(app)
    bridge = get_bridge()

    # Start the bridge if not already running
    if not bridge.running:
        bridge.start()

    @sock.route("/ws/navigation")
    def navigation_ws(ws):
        """WebSocket endpoint for navigation visualization"""
        bridge.add_client(ws)
        try:
            # Keep connection alive and handle incoming messages (if any)
            while True:
                # Use short timeout for better responsiveness on disconnect
                data = ws.receive(timeout=0.1)
                if data is None:
                    # Timeout - connection still alive, continue
                    continue
                # We don't expect clients to send messages, but if they do, ignore them
                LOG.debug(f"Received unexpected message from client: {data}")
        except Exception as e:
            LOG.debug(f"WebSocket connection closed: {e}")
        finally:
            bridge.remove_client(ws)

    LOG.info("Registered /ws/navigation WebSocket endpoint")


def main():
    """Standalone mode for testing"""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bridge = get_bridge()
    bridge.start()

    try:
        LOG.info("Navigation WebSocket bridge running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        LOG.info("Shutting down...")
    finally:
        bridge.stop()


if __name__ == "__main__":
    main()
