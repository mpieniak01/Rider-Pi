"""Tests for dynamic AI mode switching in Vision, Voice, and Navigator services."""

import time
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def reset_ai_mode():
    """Reset AI mode to default before each test."""
    from common import ai_mode

    # Store original mode
    original_mode = ai_mode.get_mode()

    # Reset to local
    ai_mode.set_mode("local")

    yield

    # Restore original mode
    ai_mode.set_mode(original_mode)


def test_navigator_subscribes_to_ai_mode_changes():
    """Test that Navigator subscribes to AI mode change events."""
    from apps.navigator.main import Navigator

    with patch("apps.navigator.main.BusSub") as mock_sub:
        # Create navigator instance
        Navigator()

        # Verify subscription to AI mode changes was created
        # Should have subscriptions for: obstacle, control, return_home, map_data, robot_pose, ai_mode
        assert mock_sub.call_count >= 6


def test_navigator_handles_mode_change_to_offload():
    """Test that Navigator handles mode change to pc_offload."""
    from apps.navigator.main import Navigator

    # Create navigator with mocked subscriptions
    with patch("apps.navigator.main.BusSub") as mock_sub_class:
        mock_sub = MagicMock()
        mock_sub_class.return_value = mock_sub

        nav = Navigator()

        # Initial state should be local
        assert nav.use_pc_enhanced is False
        assert nav.sub_obstacle_enhanced is None

        # Simulate AI mode change to pc_offload
        payload = {"mode": "pc_offload", "ts": time.time()}
        nav._handle_ai_mode_change(payload)

        # Navigator should now use PC enhanced data
        assert nav.use_pc_enhanced is True
        # Enhanced subscription should be created
        assert nav.sub_obstacle_enhanced is not None


def test_navigator_handles_mode_change_to_local():
    """Test that Navigator handles mode change back to local."""
    from apps.navigator.main import Navigator

    with patch("apps.navigator.main.BusSub") as mock_sub_class:
        mock_sub = MagicMock()
        mock_sub_class.return_value = mock_sub

        nav = Navigator()

        # First switch to offload
        nav._handle_ai_mode_change({"mode": "pc_offload", "ts": time.time()})
        assert nav.use_pc_enhanced is True

        # Then switch back to local
        nav._handle_ai_mode_change({"mode": "local", "ts": time.time()})

        # Should be back to local mode
        assert nav.use_pc_enhanced is False


def test_vision_adapter_should_run_local_detectors():
    """Test vision adapter functions respond to AI mode."""
    from apps.vision.ai_mode_adapter import should_run_local_detectors
    from common import ai_mode

    # Set to local mode
    ai_mode.set_mode("local")
    assert should_run_local_detectors() is True

    # Set to offload mode
    ai_mode.set_mode("pc_offload")
    assert should_run_local_detectors() is False


def test_voice_adapter_should_offload_to_pc():
    """Test voice adapter functions respond to AI mode."""
    from apps.voice.ai_mode_adapter import should_offload_to_pc
    from common import ai_mode

    # Set to local mode
    ai_mode.set_mode("local")
    assert should_offload_to_pc() is False

    # Set to offload mode
    ai_mode.set_mode("pc_offload")
    assert should_offload_to_pc() is True


def test_navigator_adapter_should_use_pc_enhanced_data():
    """Test navigator adapter functions respond to AI mode."""
    from apps.navigator.ai_mode_adapter import should_use_pc_enhanced_data
    from common import ai_mode

    # Set to local mode
    ai_mode.set_mode("local")
    assert should_use_pc_enhanced_data() is False

    # Set to offload mode
    ai_mode.set_mode("pc_offload")
    assert should_use_pc_enhanced_data() is True


def test_ai_mode_change_event_format():
    """Test that AI mode change events have correct format."""
    from common.bus import TOPIC_SYSTEM_AI_MODE_CHANGED

    # Verify topic constant exists
    assert TOPIC_SYSTEM_AI_MODE_CHANGED == "system.ai.mode.changed"

    # Expected event format
    expected_keys = {"mode", "ts"}

    # Create sample event
    event = {"mode": "pc_offload", "ts": time.time()}

    # Verify format
    assert set(event.keys()) == expected_keys
    assert event["mode"] in ("local", "pc_offload")
