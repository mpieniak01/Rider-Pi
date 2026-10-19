"""Real web-audio helpers with fake model providers and byte-only audio I/O."""

from __future__ import annotations

import builtins
import functools
import os
import struct
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from flask import Flask, jsonify, request
from test_gate_audio_coverage import context as context

from apps.voice import web_audio as audio


@pytest.fixture
def models(context, tmp_path, monkeypatch):
    state = SimpleNamespace(
        voice_loads=[], model_loads=[], recognizers=[], result='{"text":"  fixture transcript  "}', failure=None
    )

    class PiperVoice:
        @staticmethod
        def load(path):
            state.voice_loads.append(path)
            return SimpleNamespace(model_path=path)

    class Model:
        def __init__(self, path):
            state.model_loads.append(path)
            self.path = path

    def create_recognizer(model, rate):
        captured = SimpleNamespace(model=model, rate=rate, pcm=None)
        state.recognizers.append(captured)

        def accept_waveform(pcm):
            if state.failure is not None:
                raise state.failure
            captured.pcm = pcm

        return SimpleNamespace(AcceptWaveform=accept_waveform, FinalResult=lambda: state.result)

    piper = ModuleType("apps.voice.piper_compat")
    piper.PiperVoice = PiperVoice
    vosk = ModuleType("vosk")
    vosk.Model, vosk.KaldiRecognizer = Model, create_recognizer
    monkeypatch.setitem(sys.modules, "apps.voice.piper_compat", piper)
    monkeypatch.setitem(sys.modules, "vosk", vosk)
    context._PIPER_OK = context._VOSK_OK = False
    context._local_piper_voice = context._local_vosk_model = None
    context.PIPER_MODEL_DIR = str(tmp_path)
    context.PIPER_MODEL = str(tmp_path / "fixture.onnx")
    context.PIPER_VOICE = "environment.onnx"
    context.VOSK_MODEL = str(tmp_path / "vosk")
    Path(context.PIPER_MODEL).write_bytes(b"inert model marker")
    Path(context.VOSK_MODEL).mkdir()
    context.os.path = SimpleNamespace(isfile=os.path.isfile, isdir=os.path.isdir)
    for name in [
        "_load_piper_backend",
        "_load_vosk_backend",
        "_resolve_piper_model_path",
        "_get_local_piper_voice",
        "_get_local_vosk_model",
    ]:
        setattr(context, name, functools.partial(getattr(audio, name), context))
    context.jsonify = jsonify
    context.request = request
    return context, state


@pytest.mark.parametrize("provider,flag", [("piper", "_PIPER_OK"), ("vosk", "_VOSK_OK")])
def test_backend_import_is_cached_without_loading_any_model(models, monkeypatch, provider, flag):
    context, state = models
    loader = getattr(audio, "_load_" + provider + "_backend")
    assert loader(context) is True
    assert getattr(context, flag) is True
    module_name = "vosk" if provider == "vosk" else "apps.voice.piper_compat"
    monkeypatch.setitem(sys.modules, module_name, None)
    assert loader(context) is True
    assert state.voice_loads == []
    assert state.model_loads == []
    assert state.recognizers == []


@pytest.mark.parametrize("provider,flag", [("piper", "_PIPER_OK"), ("vosk", "_VOSK_OK")])
@pytest.mark.parametrize("error_type", [ImportError, OSError])
def test_backend_import_failures_do_not_claim_availability(context, monkeypatch, provider, flag, error_type):
    context._PIPER_OK = context._VOSK_OK = False
    module_name = "vosk" if provider == "vosk" else "apps.voice.piper_compat"
    original_import = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == module_name:
            raise error_type("inert backend unavailable")
        return original_import(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", unavailable)
        result = getattr(audio, "_load_" + provider + "_backend")(context)
    assert result is False
    assert getattr(context, flag) is False


@pytest.mark.parametrize(
    "model,payload,voice,filename",
    [
        ("explicit.onnx", "payload.onnx", "env.onnx", "explicit.onnx"),
        ("", "payload.onnx", "env.onnx", "payload.onnx"),
        ("", None, "env.onnx", "env.onnx"),
        ("", None, "", "pl_PL-mls-medium.onnx"),
    ],
)
def test_piper_model_path_precedence(models, model, payload, voice, filename):
    context, _ = models
    context.PIPER_MODEL, context.PIPER_VOICE = model, voice
    expected = model if model else context.PIPER_MODEL_DIR + "/" + filename
    assert audio._resolve_piper_model_path(context, payload) == expected


def test_models_load_once_and_cached_instances_survive_missing_source_files(models):
    context, state = models
    voice = audio._get_local_piper_voice(context)
    model = audio._get_local_vosk_model(context)
    Path(context.PIPER_MODEL).unlink()
    Path(context.VOSK_MODEL).rmdir()
    assert audio._get_local_piper_voice(context) is voice
    assert audio._get_local_vosk_model(context) is model
    assert state.voice_loads == [context.PIPER_MODEL]
    assert state.model_loads == [context.VOSK_MODEL]
    assert state.recognizers == []


@pytest.mark.parametrize("provider", ["piper", "vosk"])
def test_missing_model_paths_are_explicit_errors_before_backend_construction(models, provider):
    context, state = models
    if provider == "piper":
        Path(context.PIPER_MODEL).unlink()
        operation = functools.partial(audio._get_local_piper_voice, context)
    else:
        Path(context.VOSK_MODEL).rmdir()
        operation = functools.partial(audio._get_local_vosk_model, context)
    with pytest.raises(RuntimeError, match="not found"):
        operation()
    assert state.voice_loads == []
    assert state.model_loads == []


@pytest.mark.parametrize("provider,module_name", [("piper", "apps.voice.piper_compat"), ("vosk", "vosk")])
def test_missing_backend_prevents_model_load(models, monkeypatch, provider, module_name):
    context, state = models
    monkeypatch.setitem(sys.modules, module_name, None)
    operation = getattr(audio, "_get_local_piper_voice" if provider == "piper" else "_get_local_vosk_model")
    with pytest.raises(RuntimeError, match="module not available"):
        operation(context)
    assert state.voice_loads == []
    assert state.model_loads == []


def call_asr(context, data, content_type="audio/wav"):
    with Flask(__name__).test_request_context("/api/asr", method="POST", data=data, content_type=content_type):
        response, status = audio.api_asr(context)
    return response.get_json(), status


def test_asr_stereo_audio_runs_real_resampling_before_fake_recognizer(models):
    context, state = models
    source_pcm = struct.pack("<" + "h" * 32, *([1000, -1000] * 16))
    wav = context._wrap_wav(source_pcm, 8000, 2)
    payload, status = call_asr(context, wav)
    assert status == 200
    assert payload == {"ok": True, "text": "fixture transcript"}
    assert len(state.recognizers) == 1
    recognizer = state.recognizers[0]
    assert recognizer.rate == 16000
    assert recognizer.model.path == context.VOSK_MODEL
    assert recognizer.pcm == b"\0\0" * 31
    assert state.model_loads == [context.VOSK_MODEL]


@pytest.mark.parametrize(
    "kind,error",
    [
        ("truncated", "invalid wav"),
        ("empty", "no audio data"),
        ("width", "expected 16-bit PCM"),
        ("unknown", "unsupported or invalid audio"),
    ],
)
def test_asr_refusals_do_not_construct_a_model_or_recognizer(models, kind, error):
    context, state = models
    inputs = {
        "truncated": b"RIFF0000WAVE",
        "empty": b"",
        "unknown": b"not audio",
        "width": context._wrap_wav(b"\x80" * 8, 16000, 1, 1),
    }
    payload, status = call_asr(context, inputs[kind])
    assert status == 400
    assert payload == {"ok": False, "error": error}
    assert state.model_loads == []
    assert state.recognizers == []


def test_asr_unavailable_backend_is_visible_and_does_not_fallback_to_model(models, monkeypatch):
    context, state = models
    monkeypatch.setitem(sys.modules, "vosk", None)
    payload, status = call_asr(context, b"not decoded")
    assert status == 500
    assert payload == {"ok": False, "error": "vosk module not available"}
    assert state.model_loads == []


@pytest.mark.parametrize("invalid_result", [False, True])
def test_asr_recognizer_errors_and_invalid_json_remain_visible(models, invalid_result):
    context, state = models
    if invalid_result:
        state.result = "not json"
    else:
        state.failure = OSError("inert recognizer failed")
    wav = context._wrap_wav(b"\0\0" * 8, 16000, 1)
    payload, status = call_asr(context, wav)
    assert status == (200 if invalid_result else 500)
    assert payload == (
        {"ok": True, "text": ""} if invalid_result else {"ok": False, "error": "inert recognizer failed"}
    )


@pytest.mark.parametrize("fail", [False, True])
def test_piper_keyword_file_api_removes_temporary_after_success_or_failure(context, tmp_path, fail):
    wav = context._wrap_wav(b"\0\0" * 8, 8000, 1)
    before = set(tmp_path.iterdir())

    def synthesize_wav(*, text, wav_file):
        assert text == "fixture text"
        if fail:
            raise OSError("inert synth failed")
        Path(wav_file).write_bytes(wav)

    voice = SimpleNamespace(synthesize_wav=synthesize_wav)
    if fail:
        with pytest.raises(RuntimeError, match="no supported method"):
            audio._piper_synthesize_wav_bytes(context, voice, "fixture text")
    else:
        assert audio._piper_synthesize_wav_bytes(context, voice, "fixture text") == (wav, 8000)
    assert set(tmp_path.iterdir()) == before
