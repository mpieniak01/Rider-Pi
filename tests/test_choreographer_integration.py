"""Integration tests for choreographer module."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


def test_choreographer_integration():
    """Test full choreographer flow with mocked bus."""
    from apps.choreographer.main import process_event

    # Mock publisher
    pub = MagicMock()

    # Load config
    from apps.choreographer.config import load_choreography_config

    config = load_choreography_config()
    mappings = config.get("mappings", [])

    # Simulate joy sentiment event
    event_topic = "events.sentiment"
    event_payload = {"sentiment": "joy", "confidence": 0.9}

    process_event(event_topic, event_payload, mappings, pub)

    # Should have published commands to face and motion
    assert pub.publish.call_count >= 1

    # Check that at least one call was to face or motion
    topics_called = [call[0][0] for call in pub.publish.call_args_list]
    assert any("face" in topic or "motion" in topic for topic in topics_called)


def test_choreographer_multiple_mappings():
    """Test that choreographer handles multiple mappings correctly."""
    from apps.choreographer.main import process_event

    pub = MagicMock()

    mappings = [
        {
            "trigger": {"topic": "events.test", "match": {"type": "A"}},
            "actions": [{"topic": "command.test.a", "payload": {"data": "A"}}],
        },
        {
            "trigger": {"topic": "events.test", "match": {"type": "B"}},
            "actions": [{"topic": "command.test.b", "payload": {"data": "B"}}],
        },
    ]

    # Process event matching first mapping
    process_event("events.test", {"type": "A"}, mappings, pub)
    assert pub.publish.call_count == 1
    assert pub.publish.call_args[0][0] == "command.test.a"

    pub.reset_mock()

    # Process event matching second mapping
    process_event("events.test", {"type": "B"}, mappings, pub)
    assert pub.publish.call_count == 1
    assert pub.publish.call_args[0][0] == "command.test.b"


def test_choreographer_no_match():
    """Test that choreographer doesn't execute actions when no match."""
    from apps.choreographer.main import process_event

    pub = MagicMock()

    mappings = [
        {
            "trigger": {"topic": "events.test", "match": {"type": "A"}},
            "actions": [{"topic": "command.test", "payload": {}}],
        }
    ]

    # Process event that doesn't match
    process_event("events.test", {"type": "B"}, mappings, pub)
    pub.publish.assert_not_called()


def test_choreographer_wildcard_topic():
    """Test choreographer with wildcard topic matching."""
    from apps.choreographer.main import process_event

    pub = MagicMock()

    mappings = [
        {
            "trigger": {"topic": "events.*", "match": {}},
            "actions": [{"topic": "command.test", "payload": {}}],
        }
    ]

    # Should match any topic starting with "events."
    process_event("events.sentiment", {"data": "test"}, mappings, pub)
    assert pub.publish.call_count == 1

    pub.reset_mock()

    process_event("events.nlu.emotion", {"data": "test"}, mappings, pub)
    assert pub.publish.call_count == 1


def test_choreographer_timestamp_added():
    """Test that timestamp is added to published commands."""
    from apps.choreographer.main import execute_action

    pub = MagicMock()
    action = {"topic": "test.topic", "payload": {"key": "value"}}

    execute_action(pub, action)

    # Check that add_ts=True was passed
    pub.publish.assert_called_once()
    call_kwargs = pub.publish.call_args[1]
    assert call_kwargs.get("add_ts") is True


def test_config_has_required_mappings():
    """Test that default config has expected choreography mappings."""
    from apps.choreographer.config import load_choreography_config

    config = load_choreography_config()
    mappings = config.get("mappings", [])

    # Should have at least one mapping for joy
    joy_mappings = [m for m in mappings if m.get("trigger", {}).get("match", {}).get("sentiment") in ["joy", ["joy"]]]
    assert len(joy_mappings) > 0

    # Joy mapping should have actions
    for mapping in joy_mappings:
        actions = mapping.get("actions", [])
        assert len(actions) > 0


def test_error_handling_invalid_action():
    """Test that invalid actions don't crash the choreographer."""
    from apps.choreographer.main import execute_action

    pub = MagicMock()

    # Action without topic
    action = {"payload": {"key": "value"}}
    execute_action(pub, action)
    pub.publish.assert_not_called()

    # Action with topic but pub.publish raises exception
    pub.publish.side_effect = Exception("Test error")
    action = {"topic": "test", "payload": {}}

    # Should not raise exception
    execute_action(pub, action)
