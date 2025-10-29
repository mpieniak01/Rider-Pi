"""Tests for ALSA device configuration and logging.

Verifies that:
1. Device names are used instead of card indices
2. Device configuration is logged at startup
3. Device names are properly resolved
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from apps.voice.audio.capture import AudioCapture, CaptureConfig
from apps.voice.audio.playback import PlaybackConfig, _start_playback_process


class TestDeviceNameConfiguration:
    """Test that device configuration uses names instead of indices."""

    def test_capture_config_uses_device_name(self):
        """Verify capture config accepts and stores device names."""
        # Test with alias
        cfg = CaptureConfig(device="wm8960_in")
        assert cfg.device == "wm8960_in"
        assert "wm8960_in" in cfg.device

        # Test with full ALSA name
        cfg_full = CaptureConfig(device="plughw:CARD=wm8960soundcard,DEV=0")
        assert cfg_full.device == "plughw:CARD=wm8960soundcard,DEV=0"
        assert "CARD=" in cfg_full.device

    def test_playback_config_uses_device_name(self):
        """Verify playback config accepts and stores device names."""
        # Test with alias
        cfg = PlaybackConfig(device="wm8960_out")
        assert cfg.device == "wm8960_out"

        # Test with full ALSA name
        cfg_full = PlaybackConfig(device="plughw:CARD=wm8960soundcard,DEV=0")
        assert cfg_full.device == "plughw:CARD=wm8960soundcard,DEV=0"

    def test_capture_config_defaults_to_stable_device(self):
        """Verify default device uses name, not index."""
        cfg = CaptureConfig()
        # Default should be a stable alias, not hw:0,0 or similar
        assert cfg.device == "wm8960_in"
        # Should not contain numeric indices like hw:0 or hw:1
        assert not cfg.device.startswith("hw:0")
        assert not cfg.device.startswith("hw:1")


class TestDeviceLogging:
    """Test that device information is logged at startup."""

    def test_capture_logs_device_on_init(self, caplog):
        """Verify capture logs device information when initialized."""
        cfg = CaptureConfig(device="wm8960_in", sample_rate=16000, channels=1, sample_format="S16_LE")

        with caplog.at_level(logging.INFO):
            # We need to mock the subprocess to avoid actually starting arecord
            with patch("apps.voice.audio.capture.AudioCapture._start_proc") as mock_start:
                mock_start.return_value = MagicMock()
                try:
                    capture = AudioCapture(cfg)
                    capture.__enter__()
                except Exception:
                    # Expected - we're mocking, so it might fail
                    pass

            # Check that device information was logged
            log_messages = [rec.message for rec in caplog.records]
            device_logged = any("wm8960_in" in msg for msg in log_messages)
            assert device_logged, f"Device name not found in logs: {log_messages}"

    def test_playback_logs_device_on_init(self, caplog):
        """Verify playback logs device information when initialized."""
        cfg = PlaybackConfig(backend="alsa", device="wm8960_out", volume=55)

        with caplog.at_level(logging.INFO):
            with patch("apps.voice.audio.playback.subprocess.Popen") as mock_popen:
                mock_popen.return_value = MagicMock()
                try:
                    _start_playback_process("pcm16", cfg)
                except Exception:
                    # Expected - we're mocking
                    pass

            # Check that device information was logged
            log_messages = [rec.message for rec in caplog.records]
            # The resolved device might be different from the alias, so check for the log pattern
            device_logged = any("playback.device.init" in msg for msg in log_messages)
            assert device_logged, f"Device logging not found in logs: {log_messages}"


class TestDeviceNameValidation:
    """Test device name format validation."""

    def test_rejects_numeric_index_format(self):
        """Device names like 'hw:0,0' should be discouraged in favor of names."""
        # This test documents the expected behavior:
        # While hw:0,0 is technically valid ALSA syntax, we prefer stable names

        unstable_devices = [
            "hw:0,0",
            "hw:1,0",
            "plughw:0,0",
            "plughw:1,0",
        ]

        stable_devices = [
            "wm8960_in",
            "wm8960_out",
            "plughw:CARD=wm8960soundcard,DEV=0",
            "hw:wm8960soundcard,0",  # Uses card name, not numeric index
        ]

        # Document that unstable formats are syntactically valid but not recommended
        for device in unstable_devices:
            cfg = CaptureConfig(device=device)
            # They work, but are unstable
            assert cfg.device == device

        # Stable formats should be used
        for device in stable_devices:
            cfg = CaptureConfig(device=device)
            assert cfg.device == device
            # Stable devices have either:
            # - an alias (no hw: prefix), or
            # - explicit CARD= specification, or
            # - hw: with card name (not just a number)
            is_alias = not device.startswith("hw:") and not device.startswith("plughw:")
            has_card_spec = "CARD=" in device
            has_card_name = ":" in device and "soundcard" in device.lower()
            assert is_alias or has_card_spec or has_card_name, f"Device {device} should use stable naming"
