"""Tests for choreographer configuration loading and validation."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

def test_load_default_config():
    """Test loading default choreography config."""
    from apps.choreographer.config import load_choreography_config
    
    config = load_choreography_config()
    assert isinstance(config, dict)


def test_load_custom_config():
    """Test loading custom config from specified path."""
    from apps.choreographer.config import load_choreography_config
    
    # Create temporary config file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
        f.write("""
[[mappings]]
name = "test"
[mappings.trigger]
topic = "test.topic"
[mappings.trigger.match]
field = "value"
[[mappings.actions]]
topic = "test.action"
[mappings.actions.payload]
key = "value"
""")
        config_path = f.name
    
    try:
        config = load_choreography_config(config_path)
        assert "mappings" in config
        assert len(config["mappings"]) == 1
        assert config["mappings"][0]["name"] == "test"
    finally:
        os.unlink(config_path)


def test_load_nonexistent_config():
    """Test loading config from nonexistent path returns empty config."""
    from apps.choreographer.config import load_choreography_config
    
    config = load_choreography_config("/nonexistent/path/config.toml")
    assert config == {"mappings": []}


def test_validate_valid_config():
    """Test validation of valid config."""
    from apps.choreographer.config import validate_config
    
    config = {
        "mappings": [
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
    }
    
    assert validate_config(config) is True


def test_validate_missing_mappings():
    """Test validation fails when mappings key is missing."""
    from apps.choreographer.config import validate_config
    
    config = {}
    assert validate_config(config) is False


def test_validate_missing_trigger():
    """Test validation fails when trigger is missing."""
    from apps.choreographer.config import validate_config
    
    config = {
        "mappings": [
            {
                "actions": []
            }
        ]
    }
    assert validate_config(config) is False


def test_validate_missing_actions():
    """Test validation fails when actions are missing."""
    from apps.choreographer.config import validate_config
    
    config = {
        "mappings": [
            {
                "trigger": {
                    "topic": "test",
                    "match": {}
                }
            }
        ]
    }
    assert validate_config(config) is False


def test_validate_incomplete_trigger():
    """Test validation fails when trigger is incomplete."""
    from apps.choreographer.config import validate_config
    
    config = {
        "mappings": [
            {
                "trigger": {
                    "topic": "test"
                    # missing "match"
                },
                "actions": []
            }
        ]
    }
    assert validate_config(config) is False


def test_validate_empty_mappings():
    """Test validation succeeds with empty mappings list."""
    from apps.choreographer.config import validate_config
    
    config = {"mappings": []}
    assert validate_config(config) is True


def test_real_config_structure():
    """Test that the actual choreography.toml is valid."""
    from apps.choreographer.config import load_choreography_config, validate_config
    
    # This will load from the actual config file in the repo
    repo_root = Path(__file__).resolve().parents[1]
    config_path = str(repo_root / "config" / "choreography.toml")
    
    if os.path.exists(config_path):
        config = load_choreography_config(config_path)
        assert validate_config(config) is True
        assert "mappings" in config
        # The default config should have some mappings
        assert len(config["mappings"]) > 0
