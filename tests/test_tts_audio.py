"""Sample-level contracts for the actual TTS audio conversion layer."""

from __future__ import annotations

import struct
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.voice import tts, tts_audio as audio


def samples(*values):
    return struct.pack("<" + "h" * len(values), *values)


def test_wave_container_preserves_pcm_and_legacy_imports():
    pcm = samples(-1000, 0, 1000)
    wav = audio._wrap_wav(pcm, 8000, 1)
    assert audio._is_wav(wav)
    assert not audio._is_wav(b"RIFF1234")
    assert audio._read_wav(wav) == (pcm, 8000, 1, 2)
    assert tts._read_wav is audio._read_wav


@pytest.mark.parametrize("channels", [1, 2])
def test_fades_preserve_length_and_center_signal(channels):
    pcm = samples(*([1000] * (100 * channels)))
    faded = audio._fade_in_out(pcm, 1000, channels, 10, 10)
    values = struct.unpack("<" + "h" * (len(faded) // 2), faded)
    assert len(faded) == len(pcm)
    assert values[50 * channels] == 1000
    assert values[0] < 1000
    assert values[-1] == 0
    assert audio._fade_in_out(b"", 1000, channels) == b""
    assert audio._fade_in_out(pcm, 1000, 3) == pcm


def test_gain_normalization_and_tail_clamp_without_clipping():
    pcm = samples(-1000, 1000)
    assert audio._normalize_16bit(b"") == b""
    assert audio._normalize_16bit(pcm, target_peak=1000) == pcm
    assert audio._normalize_16bit(pcm, target_peak=2000) == samples(-2000, 2000)
    assert audio._normalize_16bit(samples(10000), target_peak=30000, extra_gain=2) == samples(32767)
    assert audio._maybe_gain(pcm, 1.0) == pcm
    assert audio._maybe_gain(pcm, 2.0) == samples(-2000, 2000)
    assert audio._append_tail(pcm, 1000, 1, 2) == pcm + b"\0" * 4
    assert audio._append_tail(pcm, 1000, 1, 0) == pcm


@pytest.mark.parametrize("input_channels,output_channels", [(1, 1), (1, 2), (2, 1)])
def test_resampling_reports_actual_rate_and_channel_count(input_channels, output_channels):
    pcm = samples(*([1000, -1000] * 20 * input_channels))
    assert audio._resample_to(pcm, 8000, input_channels, 8000, input_channels) == (pcm, 8000, input_channels)
    result, rate, channels = audio._resample_to(pcm, 8000, input_channels, 16000, output_channels)
    assert (rate, channels) == (16000, output_channels)
    assert len(result) % (2 * channels) == 0
    assert len(result) > len(pcm) // input_channels


@pytest.mark.parametrize("available", ["ffmpeg", "mpg123", None])
def test_decoder_uses_fixed_argv_and_audio_stdin(monkeypatch, available):
    import shutil
    import subprocess

    wav = audio._wrap_wav(samples(100), 8000, 1)
    monkeypatch.setattr(shutil, "which", lambda name: name if name == available else None)
    runner = Mock(return_value=SimpleNamespace(stdout=wav))
    monkeypatch.setattr(subprocess, "run", runner)
    logger = SimpleNamespace(event=Mock())
    assert audio._decode_mp3_to_wav(b"encoded", logger) == (wav if available else None)
    if available:
        args, kwargs = runner.call_args
        assert args[0][0] == available
        assert kwargs["input"] == b"encoded"
        assert kwargs["check"] is True
        runner.side_effect = OSError("decoder failed")
        assert audio._decode_mp3_to_wav(b"encoded", logger) is None
        logger.event.assert_called_once()
    else:
        runner.assert_not_called()
