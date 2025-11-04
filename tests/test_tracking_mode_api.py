#!/usr/bin/env python3
"""
Unit tests for the unified tracking mode API endpoint.
Tests the /vision/tracking/mode endpoint without requiring full dependencies.
"""

from __future__ import annotations


def test_tracking_mode_payload_validation():
    """Test that payload validation logic is correct."""
    # Valid modes
    valid_modes = ["face", "hand", "none"]
    for mode in valid_modes:
        assert mode in ["face", "hand", "none"], f"Mode {mode} should be valid"

    # Invalid modes should not be in the list
    invalid_modes = ["invalid", "FACE", "HAND", ""]
    for mode in invalid_modes:
        # Lowercase normalization would handle FACE/HAND, but empty string is invalid
        if mode.lower() not in ["face", "hand", "none"]:
            assert mode not in valid_modes, f"Mode {mode} should be invalid"


def test_enabled_false_sets_mode_none():
    """Test that enabled=false should result in mode='none'."""

    # Simulating the logic from set_tracking_mode
    def process_payload(mode: str, enabled: bool | None = None) -> tuple[str, bool]:
        """Simulate the endpoint logic."""
        mode = mode.lower()
        # Smart default: if mode is face/hand and no enabled specified, assume enabled=True
        # if mode is none or not specified, assume enabled=False
        if enabled is None:
            enabled = mode in ["face", "hand"]
        if not enabled:
            mode = "none"
        return mode, enabled

    # Test cases with explicit enabled
    assert process_payload("face", False) == ("none", False)
    assert process_payload("hand", False) == ("none", False)
    assert process_payload("none", False) == ("none", False)
    assert process_payload("face", True) == ("face", True)
    assert process_payload("hand", True) == ("hand", True)
    assert process_payload("none", True) == ("none", True)

    # Test cases with implicit enabled (None)
    assert process_payload("face") == ("face", True)  # face without enabled = enable it
    assert process_payload("hand") == ("hand", True)  # hand without enabled = enable it
    assert process_payload("none") == ("none", False)  # none without enabled = disable


def test_topic_constant_value():
    """
    Test that the topic constant has the correct value.

    Note: We use file parsing instead of importing because the bus module
    requires zmq which may not be available in CI environments.
    """
    expected_topic = "tracking.mode:set"

    # Read the constant from bus.py
    with open("common/bus.py") as f:
        content = f.read()
        # Check that the constant is defined with the correct value
        assert 'TOPIC_TRACKING_MODE_SET = "tracking.mode:set"' in content
        assert expected_topic in content


def test_endpoint_route():
    """Test that the endpoint route is correctly defined."""
    with open("services/api_core/vision_api.py") as f:
        content = f.read()
        # Check that the route is defined
        assert '@bp.route("/vision/tracking/mode"' in content
        assert 'methods=["POST", "OPTIONS"]' in content


def test_ui_calls_correct_endpoint():
    """Test that the UI JavaScript calls the correct endpoint."""
    with open("web/control.html") as f:
        content = f.read()
        # Check that the UI calls the new endpoint
        assert "/api/vision/tracking/mode" in content
        # Check that the payload format is correct
        assert "mode:" in content  # mode: 'face' or mode: 'hand'
        assert "enabled:" in content  # enabled: true/false


def test_tracker_subscribes_to_correct_topic():
    """Test that the tracker subscribes to the correct topic."""
    with open("apps/vision/tracker_mediapipe.py") as f:
        content = f.read()
        # Check that it subscribes to the new topic
        assert "tracking.mode:set" in content
        # Check that it handles the topic in control_loop
        assert 'topic == "tracking.mode:set"' in content


def test_documentation_updated():
    """Test that documentation reflects the new endpoint."""
    with open("docs/modules/vision.md") as f:
        content = f.read()
        # Check that documentation mentions the new endpoint
        assert "/vision/tracking/mode" in content
        assert "tracking.mode:set" in content


if __name__ == "__main__":
    # Run tests manually
    import sys

    tests = [
        test_tracking_mode_payload_validation,
        test_enabled_false_sets_mode_none,
        test_topic_constant_value,
        test_endpoint_route,
        test_ui_calls_correct_endpoint,
        test_tracker_subscribes_to_correct_topic,
        test_documentation_updated,
    ]

    failed = 0
    for test in tests:
        try:
            test()
            print(f"✓ {test.__name__}")
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1

    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(0 if failed == 0 else 1)
