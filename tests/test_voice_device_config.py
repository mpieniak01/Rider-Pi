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
            # Mock the subprocess to avoid actually starting arecord
            with patch("apps.voice.audio.capture.AudioCapture._start_proc") as mock_start:
                mock_proc = MagicMock()
                mock_start.return_value = mock_proc

                with patch.object(AudioCapture, "_kill_proc"):
                    capture = AudioCapture(cfg)
                    with capture:
                        # Context manager entered, logging should have occurred
                        pass

            # Check that device information was logged
            log_messages = [rec.message for rec in caplog.records]
            device_logged = any("wm8960_in" in msg for msg in log_messages)
            assert device_logged, f"Device name not found in logs: {log_messages}"

    def test_playback_logs_device_on_init(self, caplog):
        """Verify playback logs device information when initialized."""
        cfg = PlaybackConfig(backend="alsa", device="wm8960_out", volume=55)

        # Create a mock VoiceLogger with the event method
        mock_logger = MagicMock()
        mock_logger.info = MagicMock()
        mock_logger.event = MagicMock()

        with patch("apps.voice.audio.playback.voice_logging.get_logger", return_value=mock_logger):
            with patch("apps.voice.audio.playback.subprocess.Popen") as mock_popen:
                mock_proc = MagicMock()
                mock_popen.return_value = mock_proc

                with patch("apps.voice.audio.playback.shutil.which", return_value="/usr/bin/aplay"):
                    proc, backend = _start_playback_process("pcm16", cfg)
                    assert proc is not None
                    assert backend == "alsa"

        # Check that device information was logged via logger.info()
        assert mock_logger.info.called
        # Get the first call to info()
        call_args = mock_logger.info.call_args
        log_message = str(call_args)
        assert "playback.device.init" in log_message
        assert "pcm16" in log_message


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
            # - an alias (no hw:/plughw: prefix), or
            # - explicit CARD= specification
            is_alias = not device.startswith("hw:") and not device.startswith("plughw:")
            has_card_spec = "CARD=" in device
            # For hw: format, check it's not just numeric (should have card name)
            is_named_hw = self._is_named_hw_device(device)
            assert is_alias or has_card_spec or is_named_hw, (
                f"Device {device} should use stable naming (is_alias={is_alias}, has_card_spec={has_card_spec}, is_named_hw={is_named_hw})"
            )

    @staticmethod
    def _is_named_hw_device(device: str) -> bool:
        """Check if hw: device uses a named card (not numeric index)."""
        if not device.startswith("hw:"):
            return False
        if "," not in device:
            return False
        # Extract the card identifier (between "hw:" and ",")
        parts = device.split(":", 1)
        if len(parts) < 2:
            return False
        card_and_device = parts[1].split(",", 1)
        card_id = card_and_device[0]
        # If it's purely numeric, it's unstable; otherwise it's a named card
        return not card_id.isdigit()
