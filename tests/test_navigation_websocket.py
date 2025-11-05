"""
Tests for navigation WebSocket bridge.

Verifies:
- WebSocket bridge initialization and lifecycle
- Data transformation from bus topics to WebSocket format
- Message broadcasting to multiple clients
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest


def test_bridge_initialization():
    """Test that the bridge can be initialized"""
    from services.navigation_websocket_bridge import NavigationWebSocketBridge

    bridge = NavigationWebSocketBridge()
    assert bridge is not None
    assert bridge.running is False
    assert len(bridge.clients) == 0


def test_bridge_start_stop():
    """Test bridge lifecycle - start and stop"""
    from services.navigation_websocket_bridge import NavigationWebSocketBridge

    bridge = NavigationWebSocketBridge()

    # Mock BusSub to avoid actual ZMQ connections
    with patch("services.navigation_websocket_bridge.BusSub"):
        bridge.start()
        assert bridge.running is True
        assert bridge.bus_thread is not None

        # Give thread time to start
        time.sleep(0.1)

        bridge.stop()
        assert bridge.running is False


def test_handle_pose_transformation():
    """Test that odometry data is correctly transformed for frontend"""
    from services.navigation_websocket_bridge import NavigationWebSocketBridge

    bridge = NavigationWebSocketBridge()

    # Mock payload from odometry (using fixed timestamp for deterministic tests)
    odometry_payload = {"x": 1.5, "y": 2.3, "theta": 0.785, "theta_deg": 45.0, "ts": 1234567890.0}

    # Test the transformation
    bridge._handle_pose(odometry_payload)

    # Verify last_pose is set correctly
    assert bridge.last_pose is not None
    assert bridge.last_pose["x"] == 1.5
    assert bridge.last_pose["y"] == 2.3
    assert bridge.last_pose["angle"] == 0.785


def test_handle_map_transformation():
    """Test that mapper data is correctly transformed for frontend"""
    from services.navigation_websocket_bridge import NavigationWebSocketBridge

    bridge = NavigationWebSocketBridge()

    # Mock payload from mapper (using fixed timestamp for deterministic tests)
    mapper_payload = {
        "grid": [[0, 127, 255], [255, 0, 127]],  # 2x3 grid
        "width_cells": 3,
        "height_cells": 2,
        "resolution_m": 0.05,
        "origin_x": 5.0,
        "origin_y": 5.0,
        "ts": 1234567890.0,
    }

    # Test the transformation
    bridge._handle_map(mapper_payload)

    # Verify last_map is set correctly
    assert bridge.last_map is not None
    assert bridge.last_map["width"] == 3
    assert bridge.last_map["height"] == 2

    # Check grid transformation (0→2, 127→-1, 255→1)
    expected_grid = [2, -1, 1, 1, 2, -1]
    assert bridge.last_map["data"] == expected_grid


def test_client_management():
    """Test adding and removing WebSocket clients"""
    from services.navigation_websocket_bridge import NavigationWebSocketBridge

    bridge = NavigationWebSocketBridge()

    # Create mock WebSocket clients
    ws1 = MagicMock()
    ws2 = MagicMock()

    # Add clients
    bridge.add_client(ws1)
    assert len(bridge.clients) == 1

    bridge.add_client(ws2)
    assert len(bridge.clients) == 2

    # Remove client
    bridge.remove_client(ws1)
    assert len(bridge.clients) == 1
    assert ws2 in bridge.clients

    # Remove non-existent client (should not raise error)
    bridge.remove_client(ws1)
    assert len(bridge.clients) == 1


def test_broadcast_to_clients():
    """Test that messages are broadcast to all connected clients"""
    from services.navigation_websocket_bridge import NavigationWebSocketBridge

    bridge = NavigationWebSocketBridge()

    # Create mock clients
    ws1 = MagicMock()
    ws2 = MagicMock()
    bridge.add_client(ws1)
    bridge.add_client(ws2)

    # Broadcast a message
    test_message = {"type": "test", "data": {"value": 123}}
    bridge._broadcast(test_message)

    # Verify both clients received the message
    ws1.send.assert_called_once()
    ws2.send.assert_called_once()

    # Verify message content
    sent_data1 = json.loads(ws1.send.call_args[0][0])
    sent_data2 = json.loads(ws2.send.call_args[0][0])
    assert sent_data1 == test_message
    assert sent_data2 == test_message


def test_new_client_receives_last_data():
    """Test that new clients receive the last known data"""
    from services.navigation_websocket_bridge import NavigationWebSocketBridge

    bridge = NavigationWebSocketBridge()

    # Set some last known data
    bridge.last_pose = {"x": 1.0, "y": 2.0, "angle": 0.5}
    bridge.last_map = {"width": 10, "height": 10, "data": []}

    # Create mock client
    ws = MagicMock()

    # Add client
    bridge.add_client(ws)

    # Verify client received last known data (2 calls: pose and map)
    assert ws.send.call_count == 2

    # Verify message types
    calls = [json.loads(call[0][0]) for call in ws.send.call_args_list]
    types = [call["type"] for call in calls]
    assert "odometry" in types
    assert "map" in types
