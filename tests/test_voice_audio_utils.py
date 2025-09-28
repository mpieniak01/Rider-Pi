"""Test suite for audio utilities (wavutil, ALSA)."""

import os
import tempfile
import wave
from unittest.mock import patch, MagicMock

import pytest

from apps.voice.audio import alsa, wavutil
from apps.voice.errors import ALSAError


class TestWavUtil:
    """Test WAV/PCM utilities."""

    def test_is_wav_valid(self):
        """Test WAV format detection."""
        # Create simple WAV header
        wav_header = b"RIFF\x24\x00\x00\x00WAVE"
        assert wavutil.is_wav(wav_header)

    def test_is_wav_invalid(self):
        """Test non-WAV format detection."""
        assert not wavutil.is_wav(b"not a wav file")
        assert not wavutil.is_wav(b"")

    def test_wrap_wav(self):
        """Test PCM to WAV wrapping."""
        pcm_data = b"\x00\x01\x02\x03" * 100  # Simple PCM data
        wav_bytes = wavutil.wrap_wav(pcm_data, 16000, 1, 2)
        
        # Should be valid WAV
        assert wavutil.is_wav(wav_bytes)
        
        # Should be longer than PCM data due to header
        assert len(wav_bytes) > len(pcm_data)

    def test_resample_pcm_mono_to_stereo(self):
        """Test resampling mono to stereo."""
        mono_pcm = b"\x00\x01\x02\x03" * 50  # 100 samples
        stereo_pcm = wavutil.resample_pcm(mono_pcm, 16000, 1, 16000, 2)
        
        # Stereo should be twice as large
        assert len(stereo_pcm) == len(mono_pcm) * 2

    def test_resample_pcm_stereo_to_mono(self):
        """Test resampling stereo to mono."""
        stereo_pcm = b"\x00\x01\x02\x03" * 100  # 200 samples
        mono_pcm = wavutil.resample_pcm(stereo_pcm, 16000, 2, 16000, 1)
        
        # Mono should be half as large
        assert len(mono_pcm) == len(stereo_pcm) // 2

    def test_add_tail_silence(self):
        """Test adding silence to PCM."""
        pcm_data = b"\x00\x01" * 100  # 100 samples
        with_tail = wavutil.add_tail_silence(pcm_data, 16000, 1, 100)  # 100ms tail
        
        # Should be longer
        assert len(with_tail) > len(pcm_data)
        
        # Tail should be silence (zeros)
        tail = with_tail[len(pcm_data):]
        assert tail == b"\x00\x00" * (len(tail) // 2)

    def test_apply_gain_wav_no_change(self):
        """Test gain with no change (gain=1.0)."""
        wav_data = wavutil.wrap_wav(b"\x00\x01" * 100, 16000, 1, 2)
        result = wavutil.apply_gain_wav(wav_data, 1.0)
        
        # Should not change original data significantly (except possible tail)
        original_params = wavutil.read_wav_params(wav_data)
        result_params = wavutil.read_wav_params(result)
        
        assert original_params is not None
        assert result_params is not None
        assert result_params[1] == original_params[1]  # Same sample rate
        assert result_params[2] == original_params[2]  # Same channels

    def test_choose_player_command(self):
        """Test player command selection."""
        # Should return some command or None
        result = wavutil.choose_player_command()
        assert result is None or isinstance(result, list)


class TestALSA:
    """Test ALSA utilities."""

    def test_resolved_alsa_with_alias(self):
        """Test device alias resolution."""
        resolved = alsa.resolved_alsa("wm8960_in")
        assert resolved == "hw:wm8960soundcard,0"

    def test_resolved_alsa_with_direct_name(self):
        """Test direct device name."""
        device_name = "plughw:1,0"
        resolved = alsa.resolved_alsa(device_name)
        assert resolved == device_name

    def test_resolved_alsa_with_none(self):
        """Test None input."""
        resolved = alsa.resolved_alsa(None)
        assert resolved is None

    @patch('apps.voice.audio.alsa.subprocess.run')
    def test_probe_devices_success(self, mock_run):
        """Test successful device probing."""
        # Mock successful proc calls
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="0 [wm8960soundcard]: WM8960 - WM8960"),
            MagicMock(returncode=0, stdout="card 0: device 0: playback")
        ]
        
        result = alsa.probe_devices()
        
        assert "cards" in result
        assert "devices" in result
        assert "aliases" in result
        assert len(result["cards"]) > 0
        assert len(result["devices"]) > 0

    @patch('apps.voice.audio.alsa.subprocess.run')
    def test_probe_devices_failure(self, mock_run):
        """Test device probing with failures."""
        # Mock failed proc calls
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),
            MagicMock(returncode=1, stdout="")
        ]
        
        result = alsa.probe_devices()
        
        # Should still return structure
        assert "cards" in result
        assert "devices" in result
        assert len(result["cards"]) == 0
        assert len(result["devices"]) == 0

    @patch('apps.voice.audio.alsa._test_device_access')
    @patch('apps.voice.audio.alsa._kill_processes_using_device')
    def test_ensure_free_success(self, mock_kill, mock_test):
        """Test successful device freeing."""
        mock_test.return_value = True  # Devices are free
        mock_kill.return_value = 0  # No processes killed
        
        result = alsa.ensure_free("wm8960_in", "wm8960_out")
        
        assert result["capture_free"] is True
        assert result["playback_free"] is True
        assert result["processes_killed"] == 0
        assert len(result["errors"]) == 0

    @patch('apps.voice.audio.alsa._test_device_access')
    def test_ensure_free_failure(self, mock_test):
        """Test device freeing failure."""
        mock_test.return_value = False  # Devices are blocked
        
        with pytest.raises(ALSAError):
            alsa.ensure_free("wm8960_in", "wm8960_out")

    @patch('apps.voice.audio.alsa._kill_processes_using_device')
    def test_reset_streams(self, mock_kill):
        """Test stream reset."""
        mock_kill.return_value = 2  # Killed 2 processes
        
        # Should not raise exception
        alsa.reset_streams()
        
        mock_kill.assert_called_once()