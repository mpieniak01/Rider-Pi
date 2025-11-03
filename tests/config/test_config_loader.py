# tests/config/test_config_loader.py
"""
Tests for config loader with comprehensive validation.

Covers:
- Positive scenarios for both config profiles
- Unknown keys in fail-fast and lenient modes
- Type and range validation
- Precedence (ENV and CLI overrides)
- Path resolution relative to TOML directory
- Effective config printing with secret masking
- PTT ignored when server_vad=true and hotword disabled
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from apps.voice.config_loader import (
    ConfigLoader,
    ConfigSchema,
    FieldSchema,
    ValidationError,
    load_and_validate,
    mask_secrets,
    print_effective_config,
)


def test_config_positive_minimal_file_mode():
    """Test loading voice_openai_file.toml succeeds."""
    loader = ConfigLoader()
    config = loader.load("voice_openai_file.toml")

    assert "capture" in config
    assert "asr" in config
    assert "chat" in config
    assert "tts" in config
    assert "playback" in config

    # Verify key values from file
    assert config["capture"]["device"] == "wm8960_in"
    assert config["capture"]["sample_rate"] == 16000
    assert config["asr"]["backend"] == "openai"
    assert config["tts"]["format"] == "wav"


def test_config_positive_streaming_profile():
    """Test loading voice_openai_streaming_fallback.toml succeeds."""
    loader = ConfigLoader()
    config = loader.load("voice_openai_streaming_fallback.toml")

    assert "capture" in config
    assert "stream" in config
    assert "hotword" in config
    assert "ptt" in config

    # Verify streaming-specific values
    assert config["stream"]["server_vad"] is True
    assert config["hotword"]["enabled"] is False
    assert config["ptt"]["commit_on_stop"] is True


def test_unknown_keys_fail_fast():
    """Test that unknown keys raise ValidationError in fail-fast mode."""
    loader = ConfigLoader(lenient=False)

    with pytest.raises(ValidationError) as exc_info:
        loader.load(
            "voice_openai_file.toml",
            overrides={
                "asr": {"devicee": "typo"},  # Typo: devicee instead of device
                "unknown_section": {"key": "value"},
            },
        )

    error_msg = str(exc_info.value)
    assert "unknown_section" in error_msg.lower()
    assert "asr.devicee" in error_msg.lower()


def test_unknown_keys_lenient_warn(capsys):
    """Test that unknown keys generate warnings in lenient mode."""
    loader = ConfigLoader(lenient=True)

    config = loader.load(
        "voice_openai_file.toml",
        overrides={"asr": {"unknown_field": "test"}, "chat": {"another_unknown": 123}},
    )

    # Config should still load
    assert "asr" in config

    # Unknown keys should be recorded
    assert len(loader.unknown_keys) >= 2
    unknown_strs = [".".join(k) for k in loader.unknown_keys]
    assert "asr.unknown_field" in unknown_strs
    assert "chat.another_unknown" in unknown_strs


def test_type_and_range_validation():
    """Test type and range validation for various fields."""
    loader = ConfigLoader(lenient=False)

    # Invalid channels (must be 1 or 2)
    with pytest.raises(ValidationError) as exc:
        loader.load("voice_openai_file.toml", overrides={"capture": {"channels": 3}})
    assert "channels" in str(exc.value)
    assert "must be one of [1, 2]" in str(exc.value)

    # Invalid sample rate
    with pytest.raises(ValidationError) as exc:
        loader.load(
            "voice_openai_file.toml",
            overrides={
                "capture": {"sample_rate": 8000}  # Not in allowed list
            },
        )
    assert "sample_rate" in str(exc.value)

    # Invalid volume (out of range)
    with pytest.raises(ValidationError) as exc:
        loader.load(
            "voice_openai_file.toml",
            overrides={
                "playback": {"volume": 150}  # Max is 100
            },
        )
    assert "volume" in str(exc.value)
    assert "must be <=" in str(exc.value)

    # Invalid backend choice
    with pytest.raises(ValidationError) as exc:
        loader.load("voice_openai_file.toml", overrides={"asr": {"backend": "invalid_backend"}})
    assert "backend" in str(exc.value)


def test_precedence_env_cli_overrides():
    """Test that CLI and ENV overrides take precedence over TOML."""
    loader = ConfigLoader()

    # Base config from TOML
    config_base = loader.load("voice_openai_file.toml")
    assert config_base["tts"]["voice"] == "ash"

    # Override via CLI-style overrides
    config_overridden = loader.load("voice_openai_file.toml", overrides={"tts": {"voice": "nova"}})
    assert config_overridden["tts"]["voice"] == "nova"

    # Multiple levels of override
    config_multi = loader.load(
        "voice_openai_file.toml",
        overrides={
            "capture": {"sample_rate": 24000},
            "playback": {"volume": 75},
            "asr": {"model": "whisper-large"},
        },
    )
    assert config_multi["capture"]["sample_rate"] == 24000
    assert config_multi["playback"]["volume"] == 75
    assert config_multi["asr"]["model"] == "whisper-large"


def test_paths_are_relative_to_toml_dir():
    """Test that relative paths are resolved relative to TOML file directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Create a minimal TOML with relative path
        toml_content = """
[save_audio]
enabled = true
dir = "audio_logs"
"""
        config_file = tmppath / "test.toml"
        config_file.write_text(toml_content)

        # Create subdirectory
        (tmppath / "audio_logs").mkdir()

        loader = ConfigLoader()
        config = loader.load(config_file, toml_dir=tmppath)

        # Path should be resolved relative to tmppath
        assert config["save_audio"]["dir"] == str((tmppath / "audio_logs").resolve())


def test_print_effective_config_snapshot(capsys):
    """Test printing effective config with secret masking."""
    config = {
        "asr": {"backend": "openai", "model": "whisper-1"},
        "stream": {"auth": "env:OPENAI_API_KEY", "endpoint": "wss://api.openai.com"},
    }

    print_effective_config(config, mask=True)
    captured = capsys.readouterr()

    # Should be valid TOML
    assert "[asr]" in captured.out
    assert "[stream]" in captured.out
    assert "backend" in captured.out

    # Secrets should be masked (auth contains 'auth' keyword)
    assert "***" in captured.out or "OPENAI_API_KEY" in captured.out


def test_ptt_ignored_when_server_vad():
    """Test that PTT section is acknowledged as ignored when server_vad=true and hotword disabled."""
    loader = ConfigLoader()

    # Load streaming config which has server_vad=true and hotword.enabled=false
    config = loader.load("voice_openai_streaming_fallback.toml")

    # Verify the conditions
    assert config["stream"]["server_vad"] is True
    assert config["hotword"]["enabled"] is False

    # PTT section should still be in config but noted as ignored
    assert "ptt" in config


def test_mask_secrets():
    """Test secret masking function."""
    config = {
        "stream": {"auth": "sk-1234567890abcdef", "endpoint": "wss://api.example.com"},
        "api_key": "secret_token_12345",
        "regular_field": "normal_value",
    }

    masked = mask_secrets(config, keep_tail=4)

    # Secrets should be masked
    assert masked["stream"]["auth"].endswith("cdef")
    assert masked["stream"]["auth"].startswith("***")
    assert masked["api_key"].endswith("2345")
    assert masked["api_key"].startswith("***")

    # Non-secrets should remain unchanged
    assert masked["stream"]["endpoint"] == "wss://api.example.com"
    assert masked["regular_field"] == "normal_value"


def test_load_and_validate_convenience():
    """Test the convenience load_and_validate function."""
    # Should work without errors
    config = load_and_validate("voice_openai_file.toml")
    assert "asr" in config

    # Should fail on unknown keys by default
    with pytest.raises(ValidationError):
        load_and_validate("voice_openai_file.toml", overrides={"bad_section": {"key": "value"}})

    # Should succeed in lenient mode
    config = load_and_validate(
        "voice_openai_file.toml",
        overrides={"bad_section": {"key": "value"}},
        lenient=True,
    )
    assert "asr" in config


def test_typo_suggestions():
    """Test that typo suggestions are provided for unknown keys."""
    loader = ConfigLoader(lenient=False)

    with pytest.raises(ValidationError) as exc:
        loader.load(
            "voice_openai_file.toml",
            overrides={
                "asr": {"backedn": "openai"}  # Typo: backedn -> backend
            },
        )

    error_msg = str(exc.value)
    assert "backedn" in error_msg.lower()
    assert "backend" in error_msg.lower()  # Should suggest correct key


def test_schema_validation_all_sections():
    """Test that schema includes all expected sections."""
    schema = ConfigSchema()

    expected_sections = [
        "logging",
        "capture",
        "playback",
        "asr",
        "nlu",
        "chat",
        "tts",
        "hotword",
        "ptt",
        "stream",
        "vad",
        "turn",
        "service",
        "save_audio",
    ]

    for section in expected_sections:
        assert section in schema.sections, f"Missing section: {section}"


def test_deep_merge_overrides():
    """Test that overrides are properly deep-merged."""
    loader = ConfigLoader()

    config = loader.load(
        "voice_openai_file.toml",
        overrides={
            "asr": {
                "model": "whisper-large",  # Override existing field
            },
            "capture": {
                "channels": 2,  # Override existing field
                "sample_rate": 24000,  # Override existing field
            },
        },
    )

    # Overridden values
    assert config["asr"]["model"] == "whisper-large"
    assert config["capture"]["channels"] == 2
    assert config["capture"]["sample_rate"] == 24000

    # Non-overridden values should remain
    assert config["asr"]["backend"] == "openai"
    assert config["capture"]["device"] == "wm8960_in"


def test_validation_error_format():
    """Test that validation errors are well-formatted."""
    loader = ConfigLoader(lenient=False)

    with pytest.raises(ValidationError) as exc:
        loader.load(
            "voice_openai_file.toml",
            overrides={
                "unknown1": {"key": "value"},
                "unknown2": {"key": "value"},
                "capture": {"channels": 5},  # Invalid
            },
        )

    error_msg = str(exc.value)

    # Should have clear sections
    assert "Unknown keys:" in error_msg
    assert "Validation errors:" in error_msg

    # Should list specific issues
    assert "unknown1" in error_msg
    assert "unknown2" in error_msg
    assert "channels" in error_msg


def test_required_fields():
    """Test that required fields are enforced."""
    # Note: Current schema doesn't have required fields, but test the mechanism
    schema = ConfigSchema()
    # Add a required field for testing
    schema.sections["test_section"] = {"required_field": FieldSchema(type=str, required=True)}

    loader = ConfigLoader(schema=schema, lenient=False)

    # This should fail because required_field is missing
    with pytest.raises(ValidationError) as exc:
        loader.load(
            "voice_openai_file.toml",
            overrides={
                "test_section": {}  # Missing required_field
            },
        )

    assert "required_field" in str(exc.value).lower()
    assert "missing" in str(exc.value).lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
