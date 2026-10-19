"""Audio packet regressions with fake processes, microphones and backend contexts."""

from __future__ import annotations

import io
import threading
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from apps.voice import svc_audio, svc_core, web_audio
from apps.voice.audio import alsa, capture, ownership


@pytest.mark.parametrize("alive", [False, True])
def test_alsa_process_cleanup_keeps_term_probe_and_optional_kill(monkeypatch, alive):
    runner = Mock(
        side_effect=[
            SimpleNamespace(returncode=0),
            SimpleNamespace(returncode=0 if alive else 1),
            SimpleNamespace(returncode=0),
        ]
    )
    monkeypatch.setattr(alsa.subprocess, "run", runner)
    monkeypatch.setattr(alsa, "time", SimpleNamespace(sleep=Mock()))
    monkeypatch.setattr(alsa, "logger", Mock())
    assert alsa._terminate_alsa_process("123", "arecord")
    assert [c.args[0] for c in runner.call_args_list] == (
        [["kill", "-TERM", "123"], ["kill", "-0", "123"], ["kill", "-KILL", "123"]]
        if alive
        else [["kill", "-TERM", "123"], ["kill", "-0", "123"]]
    )


def test_lsof_filter_retains_only_supported_voice_processes():
    data = "COMMAND PID\narecord 1 rest\naplay 2\napps.voice.cli 3\nother 4\nmalformed\n"
    assert list(alsa._voice_processes_from_lsof(data)) == [("1", "arecord"), ("2", "aplay"), ("3", "apps.voice.cli")]


@pytest.mark.parametrize("force", [False, True])
def test_alsa_rechecks_devices_after_cleanup(monkeypatch, force):
    access = Mock(side_effect=[False, True, True, True])
    monkeypatch.setattr(alsa, "_test_device_access", access)
    cleanup = Mock(return_value=1)
    monkeypatch.setattr(alsa, "_kill_processes_using_device", cleanup)
    monkeypatch.setattr(alsa, "resolved_alsa", lambda name: name)
    monkeypatch.setattr(alsa, "time", SimpleNamespace(sleep=Mock()))
    result = alsa.ensure_free("fake-in", "fake-out", force=force)
    assert result == {"capture_free": True, "playback_free": True, "processes_killed": 1, "errors": []}
    assert access.call_args_list == [
        call("fake-in", "capture"),
        call("fake-out", "playback"),
        call("fake-in", "capture"),
        call("fake-out", "playback"),
    ]


def test_frame_reader_accumulates_partial_reads_and_discards_incomplete_eof():
    microphone = object.__new__(capture.AudioCapture)
    microphone._stop = threading.Event()
    microphone.logger = Mock()
    process = SimpleNamespace(returncode=1, poll=lambda: 1, stderr=io.BytesIO(b"closed"))
    stdout = SimpleNamespace(read=Mock(side_effect=[b"a", b"bcd", b"x", b""]))
    assert list(microphone._read_process_frames(process, stdout, 4)) == [b"abcd"]
    microphone.logger.event.assert_called_once_with("capture.proc.exit", returncode=1, stderr="closed")


@pytest.mark.parametrize("failure", [OSError("read failed"), RuntimeError("read failed")])
def test_frame_read_failure_is_logged_and_returns_for_restart(failure):
    microphone = object.__new__(capture.AudioCapture)
    microphone._stop = threading.Event()
    microphone.logger = Mock()
    assert list(microphone._read_process_frames(object(), SimpleNamespace(read=Mock(side_effect=failure)), 4)) == []
    microphone.logger.event.assert_called_once_with("capture.read.error", error="read failed")


@pytest.mark.parametrize("length,expected", [(0, b"fallback"), (100, b""), (400, b"x" * 400)])
def test_capture_once_keeps_empty_fallback_and_minimum_clip_policy(monkeypatch, length, expected):
    cfg = SimpleNamespace(frame_ms=20, sample_rate=1000, channels=1)
    ctx = Mock(
        __enter__=Mock(return_value=SimpleNamespace(frames=lambda: iter([b"x"] * 10))),
        __exit__=Mock(return_value=False),
    )
    monkeypatch.setattr(svc_audio, "AudioCapture", lambda *_args: ctx)
    monkeypatch.setattr(svc_audio, "collect", Mock(return_value=b"x" * length))
    monkeypatch.setattr(svc_audio, "capture_with_arecord", Mock(return_value=b"fallback"))
    monkeypatch.setattr(svc_audio, "time", SimpleNamespace(sleep=Mock(), time=lambda: 0))
    result = svc_audio.capture_once(cfg, object(), 1000, {"pre_speech_wait_ms": 20, "min_capture_ms": 200}, Mock())
    assert result == expected
    assert svc_audio.capture_with_arecord.call_count == (length == 0)


@pytest.mark.parametrize("ended_at", [True, -1, float("inf"), float("nan"), "10"])
def test_ownership_rejects_invalid_completion_times_without_becoming_idle(ended_at):
    import json

    observer = object.__new__(ownership.PlaybackObserver)
    observer.boot_id = "boot"
    record = {"v": 1, "boot_id": "boot", "generation": "a" * 32, "ended_at": ended_at}
    encoded_record = json.dumps(record).encode()
    with pytest.raises(ValueError, match="completion time"):
        observer._state_from_record(encoded_record)


def test_pc_result_failure_keeps_timeout_timestamp_and_processes_next_transcript(monkeypatch):
    bridge = SimpleNamespace(
        iter_results=lambda: iter([{}, {"text": " first "}, {"transcript": "second", "speak": False}])
    )
    service = SimpleNamespace(handle_external_transcript=Mock(side_effect=[RuntimeError("first failed"), None]))
    monkeypatch.setattr(svc_core, "time", SimpleNamespace(time=Mock(side_effect=[10, 11])))
    assert svc_core._process_pc_results(service, bridge, 1) == 11
    assert service.handle_external_transcript.call_args_list == [
        call("first", language="unknown", raw={"text": " first "}, speak=True),
        call("second", language="unknown", raw={"transcript": "second", "speak": False}, speak=False),
    ]


@pytest.mark.parametrize(
    "kind,expected_status", [("none", 400), ("invalid", 400), ("raw", 200), ("wav8", 400), ("wav", 200)]
)
def test_asr_route_keeps_audio_validation_before_recognizer(kind, expected_status):
    raw = b"pcm"
    recognizer = SimpleNamespace(AcceptWaveform=Mock(), FinalResult=lambda: '{"text":" hello "}')
    context = SimpleNamespace(
        _load_vosk_backend=lambda: True,
        jsonify=lambda value: value,
        request=SimpleNamespace(
            headers={"Content-Type": "application/octet-stream"},
            files={},
            get_data=lambda **_kw: b"" if kind == "none" else raw,
        ),
        _is_wav=lambda value: value == b"wav",
        _is_mp3=lambda _value: False,
        _is_ogg=lambda _value: False,
        _wrap_wav=lambda *_args: b"wav" if kind != "invalid" else None,
        _read_wav_params=lambda _value: (raw, 16000, 1, 1 if kind == "wav8" else 2),
        _get_local_vosk_model=lambda: object(),
        KaldiRecognizer=Mock(return_value=recognizer),
    )
    payload, status = web_audio.api_asr(context)
    assert status == expected_status
    if status == 200:
        assert payload == {"ok": True, "text": "hello"}
        recognizer.AcceptWaveform.assert_called_once_with(raw)
    else:
        context.KaldiRecognizer.assert_not_called()
