"""Unit tests for audio normalization in voice streaming."""

import pytest

from apps.voice.audio.capture import CaptureConfig
from apps.voice.svc_audio import ensure_mono_16k


class TestAudioNormalization:
    """Test stereo to mono downmix functionality."""

    def test_ensure_mono_16k_empty_input(self):
        """Test handling of empty audio data."""
        cfg = CaptureConfig(channels=2, sample_rate=16000)
        result = ensure_mono_16k(b"", cfg)
        assert result == b""

    def test_ensure_mono_16k_already_mono(self):
        """Test that mono audio passes through unchanged."""
        cfg = CaptureConfig(channels=1, sample_rate=16000)
        audio_data = b"\x00\x01\x02\x03" * 10  # Some test audio data
        result = ensure_mono_16k(audio_data, cfg)
        assert result == audio_data

    def test_ensure_mono_16k_stereo_to_mono(self):
        """Test stereo to mono conversion."""
        cfg = CaptureConfig(channels=2, sample_rate=16000)

        # Create stereo test data (S16_LE format: 2 bytes per sample, 2 channels)
        # This creates 4 stereo samples: L=0x0100, R=0x0302, L=0x0504, R=0x0706...
        stereo_data = b"\x00\x01\x02\x03\x04\x05\x06\x07" * 2

        result = ensure_mono_16k(stereo_data, cfg)

        # Should be roughly half the size (mono vs stereo)
        assert len(result) <= len(stereo_data) // 2 + 1
        assert len(result) > 0

    def test_ensure_mono_16k_multichannel(self):
        """Test multi-channel (>2) to mono conversion."""
        cfg = CaptureConfig(channels=4, sample_rate=16000)
        multichannel_data = b"\x00\x01\x02\x03\x04\x05\x06\x07" * 4

        result = ensure_mono_16k(multichannel_data, cfg)

        # Should produce some result (exact behavior depends on audioop implementation)
        assert len(result) > 0
        assert len(result) <= len(multichannel_data)

    def test_ensure_mono_16k_fallback_on_error(self):
        """Test fallback behavior when audioop fails."""
        cfg = CaptureConfig(channels=2, sample_rate=16000)

        # Create data that might cause audioop.tomono to fail (odd length)
        bad_stereo_data = b"\x00\x01\x02"  # Not divisible by 4 (2 bytes * 2 channels)

        # Should not raise exception, should return some result
        result = ensure_mono_16k(bad_stereo_data, cfg)
        assert isinstance(result, bytes)


class TestAudioMetrics:
    """Test audio processing metrics and logging."""

    def test_channel_counting(self):
        """Test that channel counting works correctly."""
        mono_cfg = CaptureConfig(channels=1, sample_rate=16000)
        stereo_cfg = CaptureConfig(channels=2, sample_rate=16000)

        assert mono_cfg.channels == 1
        assert stereo_cfg.channels == 2

    def test_sample_rate_detection(self):
        """Test sample rate configuration."""
        cfg = CaptureConfig(sample_rate=16000)
        assert cfg.sample_rate == 16000

        cfg_48k = CaptureConfig(sample_rate=48000)
        assert cfg_48k.sample_rate == 48000
