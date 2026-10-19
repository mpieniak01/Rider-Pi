"""P1 contracts use inert SDKs, players, logging roots and transport constructors."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import sys
import threading
import wave
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.voice import asr, cli, kws, nlu, svc_audio, svc_file, svc_stream_runner, tts, voice_logging, web_audio
from apps.voice.audio import playback
from apps.voice.stream import svc_streaming


@pytest.mark.parametrize("value,expected", [(-1, 0), (0, 0), (0.25, 0.25), (1, 1), (2, 1)])
def test_hotword_sanitizer_preserves_threshold_boundaries(value, expected):
    config = kws.HotwordConfig(enabled=True, engine="off", sensitivity=value, threshold=value)
    result = kws.HotwordDetector._sanitize_config(None, config)
    assert result.sensitivity == expected
    assert result.threshold == expected
    assert config.sensitivity == value


def test_hotword_sanitizer_preserves_nan_instead_of_reordering_clamp_comparisons():
    config = kws.HotwordConfig(enabled=False, engine="off", sensitivity=float("nan"), threshold=float("nan"))
    result = kws.HotwordDetector._sanitize_config(None, config)
    assert math.isnan(result.sensitivity)
    assert math.isnan(result.threshold)


@pytest.mark.parametrize("text,vowel", [("naprzód", "ó"), ("naprzod", "o"), ("NAPRZÓD", "Ó")])
def test_forward_regex_keeps_capturing_groups_and_polish_ascii_alternatives(text, vowel):
    matched = nlu.COMMAND_PATTERNS["forward"].search(text)
    assert matched is not None
    assert matched.groups() == (text, vowel)
    assert nlu.COMMAND_PATTERNS["forward"].search("naprzed") is None


@pytest.mark.parametrize(
    "backend,expected", [("alsa", ["aplay", "paplay"]), ("auto", ["aplay", "paplay"]), ("pulse", ["paplay"])]
)
def test_player_backend_merge_preserves_candidate_order_and_fallback(monkeypatch, backend, expected):
    monkeypatch.setattr(playback, "_iter_aplay_commands", lambda *a, **k: iter([["aplay"]]))
    monkeypatch.setattr(playback, "_iter_paplay_commands", lambda *a: iter([["paplay"]]))
    monkeypatch.setattr(playback, "_iter_ffplay_commands", lambda: iter([["ffplay"]]))
    monkeypatch.setattr(playback, "_iter_sox_play_commands", lambda *a: iter([["play"]]))
    calls = []
    process = object()

    def spawn(command, **kwargs):
        calls.append(command[0])
        if command[0] == "aplay":
            raise OSError("inert ALSA fixture failed")
        return process

    monkeypatch.setattr(playback.subprocess, "Popen", spawn)
    result, selected = playback._start_playback_process("wav", playback.PlaybackConfig(backend=backend), Mock())
    assert result is process
    assert selected == backend
    assert calls == expected


def test_json_logging_removes_every_original_handler_before_adding_its_own(monkeypatch):
    existing = [object(), object(), object()]
    root = SimpleNamespace(handlers=existing[:], setLevel=Mock())
    root.removeHandler = root.handlers.remove
    root.addHandler = root.handlers.append
    handler = SimpleNamespace(setFormatter=Mock())
    monkeypatch.setattr(
        voice_logging, "logging", SimpleNamespace(getLogger=lambda: root, StreamHandler=lambda: handler)
    )
    assert voice_logging.setup_json_logging(20) is root
    assert root.handlers == [handler]
    root.setLevel.assert_called_once_with(20)
    handler.setFormatter.assert_called_once()


def test_stdout_log_flush_uses_snapshot_when_handlers_remove_themselves(monkeypatch):
    root = SimpleNamespace(handlers=[])
    flushed = []
    for name in ("first", "second"):
        handler = SimpleNamespace(stream=None)

        def flush(handler=handler, name=name):
            flushed.append(name)
            root.handlers.remove(handler)

        handler.flush = flush
        root.handlers.append(handler)
    added = object()
    root.addHandler = root.handlers.append
    module = SimpleNamespace(
        getLogger=lambda: root, root=root, StreamHandler=lambda _stream: added, disable=Mock(), CRITICAL=50
    )
    monkeypatch.setattr(cli, "pylog", module)
    cli._silence_logging_for_stdout()
    assert flushed == ["first", "second"]
    assert root.handlers == [added]
    module.disable.assert_called_once_with(50)


def test_openai_asr_public_logger_argument_still_accepts_keywords_without_network(monkeypatch):
    create = Mock(return_value=SimpleNamespace(text=" fixture ", language="pl"))
    sdk = ModuleType("openai")
    sdk.OpenAI = lambda **kwargs: SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    monkeypatch.setitem(sys.modules, "openai", sdk)
    monkeypatch.setenv("OPENAI_API_KEY", "inert-fixture-only")
    result = asr.transcribe(b"\0\0" * 20, 16000, asr.ASRConfig(backend="openai", language="pl"), logger=Mock())
    assert result.text == "fixture"
    assert result.language == "pl"
    arguments = create.call_args.kwargs
    assert arguments["language"] == "pl"
    assert arguments["file"].name == "input.wav"
    assert arguments["file"].getvalue().startswith(b"RIFF")


@pytest.mark.parametrize("fail", [False, True])
def test_tts_stream_keeps_default_codec_request_and_closes_sdk_context(monkeypatch, fail):
    closed = []
    response = SimpleNamespace(iter_bytes=lambda _size: iter([b"one", b"", b"two"]))

    class Context:
        def __enter__(self):
            if fail:
                raise RuntimeError("inert context failure")
            return response

        def __exit__(self, *args):
            closed.append(True)

    create = Mock(return_value=Context())
    sdk = ModuleType("openai")
    sdk.OpenAI = lambda **kwargs: SimpleNamespace(
        audio=SimpleNamespace(speech=SimpleNamespace(with_streaming_response=SimpleNamespace(create=create)))
    )
    monkeypatch.setitem(sys.modules, "openai", sdk)
    chunks = tts._openai_stream_chunks("fixture", tts.TTSConfig(timeout=2), api_key="inert")
    if fail:
        with pytest.raises(RuntimeError, match="inert context failure"):
            list(chunks)
        assert closed == []
    else:
        assert list(chunks) == [b"one", b"two"]
        assert closed == [True]
    assert create.call_args.kwargs == {"model": "gpt-4o-mini-tts", "voice": "alloy", "input": "fixture", "timeout": 2}


def test_cli_wav_sniffing_preserves_container_precedence_over_json_format_metadata(monkeypatch):
    source = cli._wrap_wav(b"\1\0" * 20, 16000, 1, 2)
    monkeypatch.setenv("VOICE_RATE", "16000")
    monkeypatch.setenv("VOICE_CHANNELS", "1")
    monkeypatch.setattr(cli, "_add_tail_silence", lambda pcm, *args: pcm)
    encoded = json.dumps({"audio": base64.b64encode(source).decode(), "sample_rate": 8000, "format": "pcm16"}).encode()
    result = cli._ensure_wav_bytes(encoded, 8000)
    assert cli._read_wav_params(result) == (b"\1\0" * 20, 16000, 1, 2)


def test_web_audio_context_adapters_keep_positional_binding_and_pure_unused_context_slots():
    context = SimpleNamespace(io=io, wave=wave)
    context._is_wav = lambda data: web_audio._is_wav(context, data)
    source = web_audio._wrap_wav(context, b"\1\0" * 5, 16000, 1)
    assert web_audio._read_wav_params(context, source) == (b"\1\0" * 5, 16000, 1, 2)
    assert web_audio._is_mp3(context, b"ID3-fixture")
    assert web_audio._is_ogg(context, b"OggS-fixture")
    assert web_audio._append_tail(context, b"\1\0", 1000, 1, 2) == b"\1\0" + b"\0" * 4


@pytest.mark.asyncio
async def test_transport_initialization_retains_coroutine_contract_without_opening_connection(monkeypatch):
    created = []
    transport = object()

    def construct(**kwargs):
        created.append(kwargs)
        return transport

    monkeypatch.setattr(svc_streaming, "ReconnectingTransport", construct)
    service = object.__new__(svc_streaming.StreamingVoiceService)
    service._get_auth_header = lambda: "inert-fixture"
    service._mask_endpoint = lambda endpoint: "masked"
    service.logger = Mock()
    service.stream_cfg = SimpleNamespace(
        endpoint="wss://inert.invalid",
        max_retries=2,
        base_ms=1,
        max_ms=2,
        ping_interval_s=3,
        chunk_ms=20,
        sample_rate=16000,
        turn_end_silence_ms=50,
        max_turn_ms=1000,
        server_vad=True,
        send_partials=False,
        barge_in=True,
    )
    assert asyncio.iscoroutinefunction(service._initialize_transport)
    assert await service._initialize_transport() is True
    assert service.transport is transport
    assert created[0]["auth_header"] == "Bearer inert-fixture"
    monkeypatch.setattr(svc_streaming, "ReconnectingTransport", Mock(side_effect=RuntimeError("fixture constructor")))
    assert await service._initialize_transport() is False
    service.logger.event.assert_any_call("transport.init.error", error="fixture constructor")


@pytest.mark.parametrize("accumulate", [False, True])
def test_speech_queue_keyword_contract_preserves_forced_nonstreaming_once_behavior(accumulate):
    service = object.__new__(svc_file.VoiceService)
    service.stop_event = threading.Event()
    seen = []
    result = tts.TTSStreamResult(ok=True)

    def enqueue(task):
        seen.append(task)
        task.result = result
        task.ack.set()

    service._speech_queue = SimpleNamespace(put=enqueue)
    assert service._request_speech(" fixture ", source="chat", accumulate=accumulate) is result
    assert seen[0].text == "fixture"
    assert seen[0].source == "chat"
    assert seen[0].accumulate is False


@pytest.mark.parametrize("name", ["run_once_file", "run_listen_file", "run_once_stream", "run_listen_stream"])
def test_documented_runner_entrypoints_keep_cfg_args_keyword_contract_without_io(monkeypatch, name):
    events = []

    class Service:
        def __init__(self, _config):
            events.append("construct")

        def once(self):
            return None

        def listen(self):
            events.append("listen")

        def stop(self):
            events.append("stop")

    module = svc_file if name.endswith("_file") else svc_stream_runner
    monkeypatch.setattr(module, "VoiceService" if name.endswith("_file") else "StreamingVoiceService", Service)
    monkeypatch.setattr("apps.voice.svc_signals.setup_signals", lambda _service: None)
    assert getattr(module, name)(cfg={}, args=SimpleNamespace()) == 0
    assert events[0] == "construct"
    if name.endswith("_stream"):
        assert events[-1] == "stop"


def test_legacy_playback_tts_stub_retains_named_noop_contract():
    assert svc_audio.playback_tts(cfg={"playback": {"volume": 1}}, audio_bytes=b"inert") is None
