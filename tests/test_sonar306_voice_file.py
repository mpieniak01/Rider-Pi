"""Software-only contracts for voice response decoding, stream fallback and file turns."""

from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from apps.voice import cli, svc_file, tts


@pytest.fixture
def logger():
    return SimpleNamespace(event=Mock(), debug=Mock())


@pytest.fixture
def wav_bytes():
    return tts._wrap_wav(b"\x10\x00" * 160, 16000, 1)


def response(body=b"", content_type="audio/wav", **kwargs):
    return SimpleNamespace(
        content=body,
        headers={"Content-Type": content_type},
        status_code=kwargs.get("status", 200),
        text=kwargs.get("text", "error"),
        json=Mock(return_value=kwargs.get("payload")),
    )


@pytest.mark.parametrize("backend", ["openai", "local"])
@pytest.mark.parametrize("kind", ["wav", "magic", "mp3", "mp3_magic", "json", "nested", "unknown"])
def test_tts_response_types_still_produce_stereo_wav(monkeypatch, logger, wav_bytes, backend, kind):
    encoded = base64.b64encode(wav_bytes).decode()
    cases = {
        "wav": response(wav_bytes),
        "magic": response(wav_bytes, "application/octet-stream"),
        "mp3": response(b"mp3", "audio/mpeg"),
        "mp3_magic": response(b"ID3data", "audio/other"),
        "json": response(content_type="application/json", payload={"audio": encoded}),
        "nested": response(content_type="application/json", payload={"audio": {"data": encoded}}),
        "unknown": response(b"other", "audio/other"),
    }
    post = Mock(return_value=cases[kind])
    monkeypatch.setattr(tts.requests, "post", post)
    monkeypatch.setattr(tts, "ensure_openai_key", lambda _logger: "fake-test-key")
    monkeypatch.setattr(tts, "_decode_mp3_to_wav", Mock(return_value=wav_bytes))
    monkeypatch.setenv("VOICE_GAIN", "1.0")
    cfg = tts.TTSConfig(backend=backend, base_url="http://fake.invalid/", timeout=3)
    audio, rate, channels, fmt = tts.synthesize("hello", cfg, logger)
    pcm, wav_rate, wav_channels, width = tts._read_wav(audio)
    assert (rate, channels, fmt) == (48000, 2, "wav")
    assert (wav_rate, wav_channels, width) == (48000, 2, 2)
    assert pcm.endswith(b"\x00" * (48000 * 2 * 2 * 300 // 1000))
    assert post.call_args.kwargs["timeout"] == 3
    if backend == "local":
        assert post.call_args.args == ("http://fake.invalid/api/tts",)


@pytest.mark.parametrize("json_payload", [False, True])
def test_only_local_backend_allows_raw_pcm_fallback(monkeypatch, logger, json_payload):
    raw = b"\x01\x00" * 10
    resp = response(raw, "audio/raw")
    if json_payload:
        resp = response(content_type="application/json", payload={"data": base64.b64encode(raw).decode()})
    monkeypatch.setattr(tts.requests, "post", Mock(return_value=resp))
    monkeypatch.setattr(tts, "_decode_mp3_to_wav", Mock(return_value=None))
    monkeypatch.setattr(tts, "ensure_openai_key", lambda _logger: "fake-test-key")
    monkeypatch.setattr(tts, "time", SimpleNamespace(sleep=Mock()))
    assert tts.synthesize("hello", tts.TTSConfig(backend="local"), logger)[1:] == (48000, 2, "wav")
    openai_config = tts.TTSConfig()
    with pytest.raises(tts.TTSError, match="OpenAI TTS request failed"):
        tts.synthesize("hello", openai_config, logger)
    assert tts.time.sleep.call_args_list == [call(0.6), call(1.2), call(1.7999999999999998)]


@pytest.mark.parametrize("failure", ["http", "network", "json", "missing_audio", "bad_wav"])
def test_openai_retries_failed_response_before_success(monkeypatch, logger, wav_bytes, failure):
    bad = {
        "http": response(status=503),
        "network": tts.requests.RequestException("offline"),
        "json": response(content_type="application/json"),
        "missing_audio": response(content_type="application/json", payload={}),
        "bad_wav": response(b"bad", "audio/wav"),
    }[failure]
    if failure == "json":
        bad.json.side_effect = ValueError("invalid JSON")
    post = Mock(side_effect=[bad, response(wav_bytes)])
    monkeypatch.setattr(tts.requests, "post", post)
    monkeypatch.setattr(tts, "ensure_openai_key", lambda _logger: "fake-test-key")
    monkeypatch.setattr(tts, "time", SimpleNamespace(sleep=Mock()))
    assert tts.synthesize("hello", tts.TTSConfig(), logger)[1:] == (48000, 2, "wav")
    assert post.call_count == 2
    tts.time.sleep.assert_called_once_with(0.6)


@pytest.mark.parametrize("transport", ["realtime", "REALTIME"])
def test_strict_transport_blocks_requests_and_playback(monkeypatch, logger, transport):
    post = Mock(side_effect=AssertionError("no HTTP"))
    monkeypatch.setattr(tts.requests, "post", post)
    cfg = tts.TTSConfig(transport=transport)
    with pytest.raises(tts.TTSError, match="REST disabled"):
        tts.synthesize("hello", cfg, logger)
    with pytest.raises(tts.TTSError, match="REST disabled"):
        tts.speak("hello", cfg, object(), logger)
    post.assert_not_called()


@pytest.mark.parametrize("failure", ["write", "close", "stderr", "backend"])
def test_stream_failure_closes_player_and_falls_back(monkeypatch, logger, failure):
    stream = SimpleNamespace(backend="fake", write=Mock(), close=Mock(return_value=(True, b"mp3", None)))
    chunks = Mock(return_value=iter([b"one", b"two"]))
    if failure == "write":
        stream.write.side_effect = tts.PlaybackError("write failed")
    elif failure == "close":
        stream.close.side_effect = OSError("close failed")
    elif failure == "stderr":
        stream.close.return_value = (False, b"mp3", "player failed")
    else:
        chunks.side_effect = tts.TTSError("backend failed")
    monkeypatch.setattr(tts, "ensure_openai_key", lambda _logger: "fake-test-key")
    monkeypatch.setattr(tts, "start_stream", Mock(return_value=stream))
    monkeypatch.setattr(tts, "_openai_stream_chunks", chunks)
    synth = Mock(return_value=(b"fallback", 16000, 1, "wav"))
    monkeypatch.setattr(tts, "synthesize", synth)
    play = Mock()
    monkeypatch.setattr(tts, "play_bytes", play)
    result = tts.speak(" hello ", tts.TTSConfig(), object(), logger, accumulate=True)
    assert result.ok
    assert result.audio == b'fallback'
    assert not result.streamed
    stream.close.assert_called_once()
    synth.assert_called_once_with("hello", tts.TTSConfig(), logger)
    play.assert_called_once()


@pytest.mark.parametrize("decoded", [True, False])
def test_successful_stream_accumulates_audio_without_second_playback(monkeypatch, logger, wav_bytes, decoded):
    stream = SimpleNamespace(backend="fake", write=Mock(), close=Mock(return_value=(True, b"mp3", None)))
    monkeypatch.setattr(tts, "ensure_openai_key", lambda _logger: "fake-test-key")
    monkeypatch.setattr(tts, "start_stream", Mock(return_value=stream))
    monkeypatch.setattr(tts, "_openai_stream_chunks", lambda *_a, **_kw: iter([b"one", b"two"]))
    monkeypatch.setattr(tts, "_decode_mp3_to_wav", lambda *_a: wav_bytes if decoded else None)
    monkeypatch.setattr(tts, "synthesize", Mock(side_effect=AssertionError("no fallback")))
    result = tts.speak("hello", tts.TTSConfig(), object(), logger, accumulate=True)
    assert result.ok
    assert result.streamed
    assert result.backend == 'fake'
    expected_audio = (wav_bytes, "wav", 16000) if decoded else (b"mp3", "mp3", 0)
    assert (result.audio, result.audio_format, result.sample_rate) == expected_audio
    assert stream.write.call_args_list == [call(b"one"), call(b"two")]


def test_async_sentences_keep_minimum_boundary_and_continue_after_failure(monkeypatch, logger):
    spoken = []
    cfg = tts.TTSConfig(transport="realtime", base_url="http://fake.invalid")
    monkeypatch.setattr(tts, "ensure_openai_key", lambda _logger: "fake-test-key")

    def fake_speak(text, config, *_args, **kwargs):
        assert config.transport == 'file'
        assert config.base_url == cfg.base_url
        assert kwargs == {"accumulate": False}
        spoken.append(text)
        if len(spoken) == 1:
            raise RuntimeError("sentence failed")

    monkeypatch.setattr(tts, "speak", fake_speak)

    async def chunks():
        for text in ["Hi.", " Longer sentence!", "", " final"]:
            yield text

    result = asyncio.run(tts.speak_stream(chunks(), cfg, object(), logger))
    assert result.ok
    assert result.streamed
    assert spoken == ["Hi. Longer sentence!", "final"]
    assert cfg.transport == "realtime"
    logger.event.assert_any_call("tts.stream_async.sentence_error", error="sentence failed")


@pytest.mark.parametrize(
    "token,expected",
    [
        ("true", True),
        ("FALSE", False),
        ("-12", -12),
        ("12", 12),
        ("1e2", 100.0),
        ("1.5", 1.5),
        ("+2", "+2"),
        ("name", "name"),
        ("1e", "1e"),
        ("", ""),
    ],
)
def test_cli_pairs_retain_conservative_value_parsing(token, expected):
    assert cli._pairs_to_dict(["nest.value=" + token, "flag"]) == {"nest": {"value": expected}, "flag": True}


def test_cli_override_order_keeps_mode_vad_hotword_and_save_options():
    args = SimpleNamespace(
        asr=["transport=file", "language=en"],
        mode="stream",
        vad=["tail_ms=350"],
        service=["turn.wait=1", "save_audio=false"],
        turn=["wait=2"],
        hotword="off",
        ptt=True,
        save_audio=["on", "recordings-dir=/tmp/fake", "off"],
        playback=["ding.enabled=false"],
        ding="on",
        lang="pl",
        log_level="DEBUG",
    )
    overrides = cli._build_overrides(args)
    assert overrides["asr"] == {"transport": "realtime", "language": "pl", "vad": {"tail_ms": 350}}
    assert overrides["chat"] == overrides["tts"] == {"transport": "realtime"}
    assert overrides["service"] == {"turn": {"wait": 2}, "save_audio": False, "recordings_dir": "/tmp/fake"}
    assert overrides["hotword"] == {"enabled": True, "engine": "ptt"}
    assert overrides["playback"] == {"ding": {"enabled": True}}


@pytest.mark.parametrize("payload", ["YQ==", {"b64": "YQ=="}, {"base64": "YQ=="}, {"data": "YQ=="}])
def test_cli_json_audio_keeps_metadata_and_nested_payloads(payload):
    data = json.dumps({"audio": payload, "sample_rate": 24000, "channels": 2, "format": "pcm16"}).encode()
    assert cli._decode_json_audio(data) == (b"a", 24000, 2, "pcm16")


@pytest.mark.parametrize(
    "data",
    [
        b"not json",
        b"{",
        b"{}",
        b'{"audio":null,"data":"YQ=="}',
        b'{"audio":{"b64":"!"}}',
        b'{"audio":4}',
        b'{"audio":"a"}',
    ],
)
def test_cli_invalid_audio_is_rejected_or_keeps_permissive_base64(data):
    result = cli._decode_json_audio(data)
    assert result == ((b"", None, None, None) if b'"!"' in data else None)


@pytest.fixture
def service(logger, monkeypatch):
    instance = object.__new__(svc_file.VoiceService)
    instance.logger = logger
    instance._publish_ui_state = Mock()
    instance._publish_transcript = Mock()
    instance._hotword_engine = "off"
    instance._capture_cfg = SimpleNamespace(sample_rate=16000)
    instance._play_cfg = object()
    instance._post_tts_mute_ms = 0
    instance._request_speech = Mock(return_value=tts.TTSStreamResult(True, None, "wav", 48000))
    monkeypatch.setattr(svc_file, "play_bytes", Mock(return_value=False))
    return instance


@pytest.mark.parametrize("engine", ["ptt", "off"])
def test_legacy_hotword_fallback_uses_empty_inert_capture(service, engine):
    service._hotword_engine = engine
    seen = []

    def wait(capture):
        if capture is None:
            raise TypeError("capture required")
        seen.extend(capture.frames())
        return True

    service._hotword = SimpleNamespace(wait=wait)
    assert service._wait_hotword_without_capture()
    assert seen == []


@pytest.mark.parametrize("speak,override,expected_requests", [(False, True, 0), (True, True, 0), (True, False, 1)])
def test_transcript_override_precedes_chat_speech_even_if_player_returns_false(
    service, speak, override, expected_requests
):
    transcript = SimpleNamespace(text="question")
    intent = SimpleNamespace(kind="chat")
    payload = {"audio": base64.b64encode(b"pc-audio").decode(), "format": "mp3", "sample_rate": 22050}
    result = service._process_transcript(
        transcript,
        speak=speak,
        intent_override=intent,
        reply_override=" answer ",
        tts_override=payload if override else None,
    )
    assert result.reply == " answer "
    assert service._request_speech.call_count == expected_requests
    if speak and override:
        assert (result.audio, result.audio_format, result.sample_rate) == (b"pc-audio", "mp3", 22050)
    if not speak:
        service._publish_ui_state.assert_called_once_with("idle")


def test_invalid_override_falls_back_to_reply_and_empty_reply_returns_idle(service):
    transcript = SimpleNamespace(text="question")
    intent = SimpleNamespace(kind="chat")
    service._process_transcript(
        transcript, speak=True, intent_override=intent, reply_override="reply", tts_override={"audio": "a"}
    )
    service._request_speech.assert_called_once_with("reply", source="chat", accumulate=False)
    service._publish_ui_state.assert_not_called()
    service._process_transcript(transcript, speak=True, intent_override=intent, reply_override="   ")
    service._publish_ui_state.assert_called_once_with("idle")


@pytest.mark.parametrize("separate_capture", [True, False])
def test_cycle_capture_retains_hotword_ding_and_microphone_order(service, monkeypatch, separate_capture):
    actions = []
    service._hotword_engine = "ptt" if separate_capture else "wake"
    service._hotword_enabled = True
    service._wait_hotword_without_capture = lambda: actions.append("wait") or True
    service._record_with_vad = lambda: actions.append("record") or b"audio"
    service._play_cycle_ding = lambda **_kw: actions.append("ding")
    service._mic_open_delay_ms = 20
    service._vad = object()
    service._max_len = 1000
    capture = SimpleNamespace(frames=lambda: iter([b"frame"]))
    context = Mock(__enter__=Mock(return_value=capture), __exit__=Mock(return_value=False))
    monkeypatch.setattr(svc_file, "AudioCapture", lambda *_args: context)
    service._hotword = SimpleNamespace(wait=lambda _capture: actions.append("wait") or True)
    monkeypatch.setattr(svc_file, "collect", lambda *_args: actions.append("record") or b"audio")
    monkeypatch.setattr(svc_file, "time", SimpleNamespace(sleep=lambda _delay: actions.append("delay")))
    assert service._capture_cycle_audio(speak=True) == b"audio"
    assert actions == (["wait", "ding", "record"] if separate_capture else ["wait", "ding", "delay", "record"])
    if not separate_capture:
        context.__exit__.assert_called_once()
