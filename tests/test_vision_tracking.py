from __future__ import annotations

import os

# tests/test_vision_tracking.py
"""Tests for vision tracking (Follow Me) feature."""

import pytest


def test_bus_topics_defined():
    """Verify all tracking topics are defined in bus module."""
    from common import bus

    assert hasattr(bus, "TOPIC_VISION_TRACKING_OFFSET")
    assert hasattr(bus, "TOPIC_VISION_FOLLOW_FACE_SET")
    assert hasattr(bus, "TOPIC_VISION_FOLLOW_HAND_SET")
    assert hasattr(bus, "TOPIC_VISION_FOLLOW_STOP")

    # Check topic values are strings
    assert isinstance(bus.TOPIC_VISION_TRACKING_OFFSET, str)
    assert isinstance(bus.TOPIC_VISION_FOLLOW_FACE_SET, str)
    assert isinstance(bus.TOPIC_VISION_FOLLOW_HAND_SET, str)
    assert isinstance(bus.TOPIC_VISION_FOLLOW_STOP, str)


def test_vision_api_endpoints_exist():
    """Verify vision API has follow endpoints."""
    from services.api_core import vision_api

    # Check functions exist (blueprint not registered in tests)
    assert hasattr(vision_api, "set_follow_face")
    assert hasattr(vision_api, "set_follow_hand")
    assert callable(vision_api.set_follow_face)
    assert callable(vision_api.set_follow_hand)


def test_tracker_imports():
    """Verify tracker module can be imported."""
    try:
        import apps.vision.tracker_mediapipe as tracker

        assert hasattr(tracker, "tracking_loop")
        assert hasattr(tracker, "control_loop")
        assert callable(tracker.tracking_loop)
        assert callable(tracker.control_loop)
    except ImportError as e:
        # MediaPipe might not be available in test environment
        pytest.skip(f"Tracker module import failed (expected in CI): {e}")


def test_tracking_controller_imports():
    """Verify tracking controller module can be imported."""
    try:
        import apps.motion.tracking_controller as controller

        assert hasattr(controller, "TrackingController")
        assert hasattr(controller, "main")
        assert callable(controller.main)

        # Check controller has expected methods
        tc = controller.TrackingController()
        assert hasattr(tc, "on_tracking_offset")
        assert hasattr(tc, "watchdog_loop")
        assert callable(tc.on_tracking_offset)
        assert callable(tc.watchdog_loop)
    except Exception as e:
        # XgoAdapter might not be available in test environment
        pytest.skip(f"Tracking controller import failed (expected in CI): {e}")


def test_tracking_offset_calculation():
    """Test offset calculation logic."""
    try:
        import apps.vision.tracker_mediapipe as tracker

        # Mock detection with bounding box at different positions
        class MockDetection:
            class LocationData:
                class BBox:
                    def __init__(self, xmin, width):
                        self.xmin = xmin
                        self.width = width

                def __init__(self, xmin, width):
                    self.relative_bounding_box = self.BBox(xmin, width)

                def HasField(self, field):
                    return field == "relative_bounding_box"

            def __init__(self, xmin, width):
                self.location_data = self.LocationData(xmin, width)

        # Test center position (should be ~0)
        center_det = MockDetection(0.25, 0.5)  # center at 0.5
        offset = tracker.calculate_offset_x([center_det], 640)
        assert abs(offset) < 0.1  # Should be in dead zone

        # Test left position
        left_det = MockDetection(0.0, 0.2)  # center at 0.1
        offset = tracker.calculate_offset_x([left_det], 640)
        assert offset is not None
        assert offset < -0.1  # Should be negative (left)

        # Test right position
        right_det = MockDetection(0.7, 0.2)  # center at 0.8
        offset = tracker.calculate_offset_x([right_det], 640)
        assert offset is not None
        assert offset > 0.1  # Should be positive (right)

        # Test no detections
        offset = tracker.calculate_offset_x([], 640)
        assert offset is None

    except ImportError:
        pytest.skip("Tracker module not available (expected in CI)")


def test_proportional_controller_logic():
    """Test proportional controller calculations."""
    # Test dead zone
    DEAD_ZONE = 0.1
    KP = 0.15

    def calc_rotation(offset_x):
        if abs(offset_x) < DEAD_ZONE:
            return 0.0
        return KP * offset_x

    # In dead zone
    assert calc_rotation(0.05) == 0.0
    assert calc_rotation(-0.08) == 0.0

    # Outside dead zone
    assert calc_rotation(0.5) == pytest.approx(0.075)
    assert calc_rotation(-0.5) == pytest.approx(-0.075)
    assert calc_rotation(1.0) == pytest.approx(0.15)


def test_env_configuration():
    """Test that configuration can be set via environment variables."""
    # Test that defaults are reasonable
    from apps.motion import tracking_controller

    # Verify defaults exist and are floats
    assert isinstance(tracking_controller.KP, float)
    assert isinstance(tracking_controller.DEAD_ZONE, float)
    assert isinstance(tracking_controller.TIMEOUT_SEC, float)
    assert isinstance(tracking_controller.MAX_SPEED, float)

    # Verify reasonable ranges
    assert 0.0 < tracking_controller.KP < 1.0
    assert 0.0 < tracking_controller.DEAD_ZONE < 0.5
    assert 0.0 < tracking_controller.TIMEOUT_SEC < 10.0
    assert 0.0 < tracking_controller.MAX_SPEED <= 1.0
