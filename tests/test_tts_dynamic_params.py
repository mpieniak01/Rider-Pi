"""Unit tests for dynamic audio parameters in TTS playback."""

from unittest.mock import MagicMock, patch

import pytest

from apps.voice.audio.playback import PlaybackConfig, _iter_aplay_commands


class TestDynamicAudioParams:
    """Test dynamic audio parameter handling."""

    @patch("apps.voice.audio.playback.shutil.which")
    def test_iter_aplay_commands_with_dynamic_wav_params(self, mock_which):
        """Test that aplay commands use dynamic parameters for WAV when provided."""
        mock_which.return_value = "/usr/bin/aplay"
        cfg = PlaybackConfig(backend="alsa", device="default")

        # Test with 24kHz mono (Google Gemini native)
        commands = list(_iter_aplay_commands(cfg, fmt="wav", sample_rate=24000, channels=1))

        assert len(commands) > 0
        # First command should have dynamic parameters
        cmd = commands[0]
        assert "/usr/bin/aplay" in cmd[0]
        assert "-f" in cmd
        assert "S16_LE" in cmd
        assert "-r" in cmd
        assert "24000" in cmd
        assert "-c" in cmd
        assert "1" in cmd

    @patch("apps.voice.audio.playback.shutil.which")
    def test_iter_aplay_commands_with_48k_stereo(self, mock_which):
        """Test that aplay commands use 48kHz/Stereo for OpenAI/Local."""
        mock_which.return_value = "/usr/bin/aplay"
        cfg = PlaybackConfig(backend="alsa", device="default")

        # Test with 48kHz stereo (OpenAI/Local)
        commands = list(_iter_aplay_commands(cfg, fmt="wav", sample_rate=48000, channels=2))

        assert len(commands) > 0
        # First command should have dynamic parameters
        cmd = commands[0]
        assert "/usr/bin/aplay" in cmd[0]
        assert "-f" in cmd
        assert "S16_LE" in cmd
        assert "-r" in cmd
        assert "48000" in cmd
        assert "-c" in cmd
        assert "2" in cmd

    @patch("apps.voice.audio.playback.shutil.which")
    def test_iter_aplay_commands_pcm16_unchanged(self, mock_which):
        """Test that PCM16 (ding) uses hardcoded 16kHz/Mono."""
        mock_which.return_value = "/usr/bin/aplay"
        cfg = PlaybackConfig(backend="alsa", device="default")

        # Test with pcm16 format (should ignore sample_rate/channels)
        commands = list(_iter_aplay_commands(cfg, fmt="pcm16", sample_rate=48000, channels=2))

        assert len(commands) > 0
        # First command should have hardcoded PCM16 parameters
        cmd = commands[0]
        assert "/usr/bin/aplay" in cmd[0]
        assert "-f" in cmd
        assert "S16_LE" in cmd
        assert "-r" in cmd
        assert "16000" in cmd
        assert "-c" in cmd
        assert "1" in cmd

    @patch("apps.voice.audio.playback.shutil.which")
    def test_iter_aplay_commands_fallback_without_params(self, mock_which):
        """Test fallback behavior when sample_rate/channels not provided."""
        mock_which.return_value = "/usr/bin/aplay"
        cfg = PlaybackConfig(backend="alsa", device="default")

        # Test without parameters (fallback to letting aplay read header)
        commands = list(_iter_aplay_commands(cfg, fmt="wav", sample_rate=None, channels=None))

        assert len(commands) > 0
        # First command should NOT have explicit format parameters beyond -q and -D
        cmd = commands[0]
        assert "/usr/bin/aplay" in cmd[0]
        assert "-q" in cmd
        # When no params provided, we use a minimal command
        # The command should be shorter than with explicit params
        assert len(cmd) < 10  # base + device should be less than 10 elements
