"""Tests for choreographer event mapping logic."""
from __future__ import annotations

def test_match_event_exact():
    """Test exact match of event payload."""
    from apps.choreographer.main import match_event
    
    event = {"sentiment": "joy", "confidence": 0.9}
    criteria = {"sentiment": "joy"}
    
    assert match_event(event, criteria) is True


def test_match_event_mismatch():
    """Test mismatch of event payload."""
    from apps.choreographer.main import match_event
    
    event = {"sentiment": "joy"}
    criteria = {"sentiment": "sad"}
    
    assert match_event(event, criteria) is False


def test_match_event_missing_field():
    """Test match fails when field is missing."""
    from apps.choreographer.main import match_event
    
    event = {"sentiment": "joy"}
    criteria = {"sentiment": "joy", "confidence": 0.9}
    
    assert match_event(event, criteria) is False


def test_match_event_wildcard():
    """Test wildcard matching."""
    from apps.choreographer.main import match_event
    
    event = {"sentiment": "joy", "confidence": 0.9}
    criteria = {"sentiment": "*"}
    
    assert match_event(event, criteria) is True


def test_match_event_list():
    """Test matching against list of values."""
    from apps.choreographer.main import match_event
    
    event = {"sentiment": "joy"}
    criteria = {"sentiment": ["joy", "happy", "excited"]}
    
    assert match_event(event, criteria) is True


def test_match_event_list_mismatch():
    """Test mismatch against list of values."""
    from apps.choreographer.main import match_event
    
    event = {"sentiment": "sad"}
    criteria = {"sentiment": ["joy", "happy", "excited"]}
    
    assert match_event(event, criteria) is False


def test_match_event_multiple_criteria():
    """Test matching multiple criteria."""
    from apps.choreographer.main import match_event
    
    event = {"sentiment": "joy", "confidence": 0.9, "source": "nlu"}
    criteria = {"sentiment": "joy", "source": "nlu"}
    
    assert match_event(event, criteria) is True


def test_match_event_empty_criteria():
    """Test empty criteria matches any event."""
    from apps.choreographer.main import match_event
    
    event = {"sentiment": "joy", "confidence": 0.9}
    criteria = {}
    
    assert match_event(event, criteria) is True


def test_process_event_no_match():
    """Test processing event with no matching choreography."""
    from apps.choreographer.main import process_event
    from unittest.mock import MagicMock
    
    pub = MagicMock()
    mappings = [
        {
            "trigger": {
                "topic": "events.sentiment",
                "match": {"sentiment": "sad"}
            },
            "actions": []
        }
    ]
    
    # Event doesn't match
    process_event("events.sentiment", {"sentiment": "joy"}, mappings, pub)
    
    # No actions should be executed
    pub.publish.assert_not_called()


def test_process_event_with_match():
    """Test processing event with matching choreography."""
    from apps.choreographer.main import process_event
    from unittest.mock import MagicMock
    
    pub = MagicMock()
    mappings = [
        {
            "trigger": {
                "topic": "events.sentiment",
                "match": {"sentiment": "joy"}
            },
            "actions": [
                {
                    "topic": "command.face.expression",
                    "payload": {"expression": "happy"}
                }
            ]
        }
    ]
    
    # Event matches
    process_event("events.sentiment", {"sentiment": "joy"}, mappings, pub)
    
    # Action should be executed
    pub.publish.assert_called_once()
    call_args = pub.publish.call_args
    assert call_args[0][0] == "command.face.expression"
    assert call_args[0][1] == {"expression": "happy"}


def test_process_event_multiple_actions():
    """Test processing event triggers multiple actions."""
    from apps.choreographer.main import process_event
    from unittest.mock import MagicMock
    
    pub = MagicMock()
    mappings = [
        {
            "trigger": {
                "topic": "events.sentiment",
                "match": {"sentiment": "joy"}
            },
            "actions": [
                {
                    "topic": "command.face.expression",
                    "payload": {"expression": "happy"}
                },
                {
                    "topic": "command.motion.action",
                    "payload": {"action": "wag"}
                }
            ]
        }
    ]
    
    process_event("events.sentiment", {"sentiment": "joy"}, mappings, pub)
    
    # Both actions should be executed
    assert pub.publish.call_count == 2


def test_process_event_wildcard_topic():
    """Test processing event with wildcard topic matching."""
    from apps.choreographer.main import process_event
    from unittest.mock import MagicMock
    
    pub = MagicMock()
    mappings = [
        {
            "trigger": {
                "topic": "events.*",
                "match": {"type": "test"}
            },
            "actions": [
                {
                    "topic": "command.test",
                    "payload": {}
                }
            ]
        }
    ]
    
    # Should match events.sentiment
    process_event("events.sentiment", {"type": "test"}, mappings, pub)
    assert pub.publish.call_count == 1
    
    pub.reset_mock()
    
    # Should match events.nlu.emotion
    process_event("events.nlu.emotion", {"type": "test"}, mappings, pub)
    assert pub.publish.call_count == 1


def test_execute_action_missing_topic():
    """Test executing action without topic logs warning."""
    from apps.choreographer.main import execute_action
    from unittest.mock import MagicMock
    
    pub = MagicMock()
    action = {
        "payload": {"key": "value"}
        # missing "topic"
    }
    
    execute_action(pub, action)
    
    # Should not publish
    pub.publish.assert_not_called()


def test_execute_action_with_payload():
    """Test executing action with payload."""
    from apps.choreographer.main import execute_action
    from unittest.mock import MagicMock
    
    pub = MagicMock()
    action = {
        "topic": "test.topic",
        "payload": {"key": "value"}
    }
    
    execute_action(pub, action)
    
    pub.publish.assert_called_once()
    call_args = pub.publish.call_args
    assert call_args[0][0] == "test.topic"
    assert call_args[0][1] == {"key": "value"}
    assert call_args[1]["add_ts"] is True
