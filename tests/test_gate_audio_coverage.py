"""Audio conversion and adapter contracts with byte buffers and fake synthesizers."""

from __future__ import annotations

import audioop
import functools
import io
import os
import struct
import tempfile
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from apps.voice import web_audio as audio


@pytest.fixture
def context(tmp_path):
    env = {
        "VOICE_RATE": "8000",
        "VOICE_CHANNELS": "1",
        "VOICE_FADE_IN_MS": "0",
        "VOICE_FADE_OUT_MS": "0",
        "VOICE_TAIL_MS": "0",
        "VOICE_GAIN": "1.0",
    }
    ctx = SimpleNamespace(
        io=io,
        wave=wave,
        struct=struct,
        audioop=audioop,
        os=SimpleNamespace(environ=env, getenv=env.get, remove=os.remove),
        tempfile=SimpleNamespace(NamedTemporaryFile=lambda **kw: tempfile.NamedTemporaryFile(dir=tmp_path, **kw)),
        shutil=SimpleNamespace(which=lambda name: None),
        subprocess=SimpleNamespace(run=Mock(), PIPE=-1, DEVNULL=-3),
    )
    for name in [
        "_is_wav",
        "_read_wav_params",
        "_wrap_wav",
        "_is_mp3",
        "_is_ogg",
        "_decode_with_tool_to_wav",
        "_apply_fade",
        "_append_tail",
        "_maybe_gain",
        "_resample_to",
    ]:
        setattr(ctx, name, functools.partial(getattr(audio, name), ctx))
    return ctx


def test_wav_roundtrip_preserves_samples_and_rejects_truncated_header(context):
    pcm = struct.pack("<hhh", -1000, 0, 1000)
    wav = context._wrap_wav(pcm, 8000, 1)
    assert context._is_wav(wav)
    assert context._read_wav_params(wav) == (pcm, 8000, 1, 2)
    assert context._read_wav_params(b"not-a-wave") is None
    assert context._read_wav_params(b"RIFF1234WAVE") is None


@pytest.mark.parametrize("kind", ["wav", "raw", "mp3", "ogg"])
def test_supported_audio_formats_normalize_to_configured_wav(context, kind):
    pcm = struct.pack("<hhhh", 100, 200, -100, -200)
    wav = context._wrap_wav(pcm, 16000, 2)
    if kind == "wav":
        source = wav
    elif kind == "raw":
        source = pcm
    else:
        source = b"ID3compressed" if kind == "mp3" else b"OggScompressed"
        context._decode_with_tool_to_wav = Mock(return_value=wav)
    result = audio._ensure_wav_bytes(context, source, 16000, kind)
    _samples, rate, channels, width = context._read_wav_params(result)
    assert (rate, channels, width) == (8000, 1, 2)


def test_undecodable_compressed_audio_does_not_become_raw_pcm(context):
    assert audio._ensure_wav_bytes(context, b"ID3broken", None, "mp3") is None
    context.subprocess.run.assert_not_called()


def test_fade_tail_and_gain_preserve_signal_contract(context):
    pcm = struct.pack("<" + "h" * 100, *([1000] * 100))
    faded = context._apply_fade(pcm, 1000, 1, 2, 10, 10)
    samples = struct.unpack("<" + "h" * 100, faded)
    assert len(faded) == len(pcm)
    assert samples[0] == 0
    assert samples[50] == 1000
    assert samples[-1] < 1000
    assert context._append_tail(b"", 1000, 2, 2) == b"\0" * 8
    assert struct.unpack("<h", context._maybe_gain(struct.pack("<h", 1000), 2))[0] == 2000
    assert context._apply_fade(b"", 1000, 1, 2, 10, 10) == b""


@pytest.mark.parametrize("which", ["mpg123", "ffmpeg"])
def test_decoder_uses_fixed_arguments_and_stdin_for_audio(context, which):
    wav = context._wrap_wav(b"\0\0", 8000, 1)
    context.shutil.which = lambda name: name if name == which else None
    context.subprocess.run.return_value = SimpleNamespace(stdout=wav)
    assert context._decode_with_tool_to_wav(b"encoded") == wav
    args, kwargs = context.subprocess.run.call_args
    assert args[0][0] == which
    assert kwargs["input"] == b"encoded"
    assert kwargs["check"] is True
    context.subprocess.run.side_effect = OSError("decoder unavailable")
    assert context._decode_with_tool_to_wav(b"encoded") is None


@pytest.mark.parametrize("tuple_result", [False, True])
def test_direct_piper_bytes_are_supported_without_audio_device(context, tuple_result):
    wav = context._wrap_wav(b"\0\0", 8000, 1)
    voice = SimpleNamespace(synthesize_wav_bytes=Mock(return_value=(wav, 8000) if tuple_result else wav))
    actual, rate = audio._piper_synthesize_wav_bytes(context, voice, "fixture")
    assert actual == wav
    assert rate == (8000 if tuple_result else None)
    voice.synthesize_wav_bytes.assert_called_once_with("fixture")


@pytest.mark.parametrize(
    "method", ["synthesize_wav", "synthesize_to_wav", "save_wav", "synthesize_to_file", "synthesize"]
)
def test_file_synthesizer_wav_is_read_and_temporary_is_removed(context, tmp_path, method):
    wav = context._wrap_wav(b"\0\0", 8000, 1)

    def synthesize(text, filename):
        assert text == "fixture"
        Path(filename).write_bytes(wav)

    voice = SimpleNamespace(**{method: synthesize})
    assert audio._piper_synthesize_wav_bytes(context, voice, "fixture") == (wav, 8000)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("pcm", [b"\0\0\0\0", [-0.2, 0.2], np.array([-0.2, 0.2]), np.array([1, 2], dtype="int16")])
def test_pcm_synthesizer_variants_are_wrapped_as_wav(context, pcm):
    voice = SimpleNamespace(tts=lambda text: (pcm, 8000))
    wav, rate = audio._piper_synthesize_wav_bytes(context, voice, "fixture")
    assert rate == 8000
    assert context._read_wav_params(wav)[1:] == (8000, 1, 2)


def test_missing_synthesizer_is_an_explicit_failure(context):
    voice = SimpleNamespace()
    with pytest.raises(RuntimeError, match="no supported method"):
        audio._piper_synthesize_wav_bytes(context, voice, "fixture")
