"""File capture contracts with fake microphone, clock, VAD and arecord."""

from __future__ import annotations

from itertools import count
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from apps.voice import svc_file_capture as capture_module
from apps.voice.audio.capture import CaptureError
from apps.voice.svc_file_capture import FileCaptureMixin


class FakeCapture:
    def __init__(self, frames):
        self._frames = frames
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True
        return False

    def frames(self):
        return iter(self._frames)


class CaptureHarness(FileCaptureMixin):
    def __init__(self):
        self._capture_cfg = SimpleNamespace(sample_rate=1000, channels=1, frame_ms=20, device=None, buffer_seconds=0)
        self._mute_until_ts = 0
        self._mic_open_delay_ms = 0
        self._no_speech_timeout_ms = 300
        self._silence_rms_gate = 1
        self._pre_speech_wait_ms = 60
        self._min_capture_ms = 200
        self._max_len = 1000
        self._vad = object()
        self.logger = SimpleNamespace(event=Mock())

    def _frame_has_voice(self, frame, _threshold):
        return frame.startswith(b"v")

    def _safe_frame_bytes(self):
        return 40


@pytest.fixture
def harness(monkeypatch):
    ticks = count(step=0.1)
    clock = SimpleNamespace(time=lambda: next(ticks), sleep=Mock())
    monkeypatch.setattr(capture_module, "time", clock)
    monkeypatch.setattr(capture_module, "collect", lambda frames, *_args: b"".join(frames))
    return CaptureHarness()


def test_voice_capture_preserves_preroll_and_tail_and_closes_microphone(harness, monkeypatch):
    frames = [b"", b"v" * 40, b"a" * 40, b"b" * 400]
    microphone = FakeCapture(frames)
    factory = Mock(return_value=microphone)
    monkeypatch.setattr(capture_module, "AudioCapture", factory)
    harness._mute_until_ts = 0.25
    harness._mic_open_delay_ms = 20
    assert harness._record_with_vad() == b"".join(frames)
    assert microphone.closed
    factory.assert_called_once()
    assert capture_module.time.sleep.call_args_list == [call(0.25), call(0.02)]


@pytest.mark.parametrize("frames", [[], [b"s" * 40] * 10])
def test_voice_no_speech_does_not_start_fallback_recorder(harness, monkeypatch, frames):
    microphone = FakeCapture(frames)
    monkeypatch.setattr(capture_module, "AudioCapture", Mock(return_value=microphone))
    harness._record_with_arecord = Mock(side_effect=AssertionError("No fallback after silence"))
    assert harness._record_with_vad() == b""
    assert microphone.closed
    harness._record_with_arecord.assert_not_called()
    harness.logger.event.assert_called_with("service.nospeech.timeout", ms=300)


def test_voice_short_preroll_keeps_available_frames(harness, monkeypatch):
    microphone = FakeCapture([b"v" * 40])
    monkeypatch.setattr(capture_module, "AudioCapture", Mock(return_value=microphone))
    assert harness._initial_vad_audio() == b"v" * 40
    assert microphone.closed


@pytest.mark.parametrize(
    ("error", "event"),
    [
        (CaptureError("capture unavailable"), "service.capture.error"),
        (OSError("capture unavailable"), "service.capture.unexpected"),
    ],
)
def test_voice_capture_errors_use_existing_fallback(harness, monkeypatch, error, event):
    monkeypatch.setattr(capture_module, "AudioCapture", Mock(side_effect=error))
    harness._record_with_arecord = Mock(return_value=b"fallback")
    assert harness._record_with_vad() == b"fallback"
    harness._record_with_arecord.assert_called_once()
    harness.logger.event.assert_any_call(event, error="capture unavailable")


def test_voice_empty_vad_result_uses_existing_fallback(harness, monkeypatch):
    monkeypatch.setattr(capture_module, "AudioCapture", Mock(return_value=FakeCapture([b"v" * 40])))
    monkeypatch.setattr(capture_module, "collect", Mock(return_value=b""))
    harness._record_with_arecord = Mock(return_value=b"fallback")
    assert harness._record_with_vad() == b"fallback"
    harness._record_with_arecord.assert_called_once()


@pytest.mark.parametrize("retry_audio", [b"r" * 400, b"r" * 100, b""])
def test_voice_retry_requires_a_longer_clip_meeting_minimum(harness, monkeypatch, retry_audio):
    first = FakeCapture([b"v" * 40])
    retry = FakeCapture([b"r" * 40] * 100)
    factory = Mock(side_effect=[first, retry])
    monkeypatch.setattr(capture_module, "AudioCapture", factory)
    collector = Mock(side_effect=[b"s" * 100, retry_audio])
    monkeypatch.setattr(capture_module, "collect", collector)
    harness._mic_open_delay_ms = 10
    expected = retry_audio if len(retry_audio) >= 400 else b""
    assert harness._record_with_vad() == expected
    assert factory.call_count == 2
    assert first.closed
    assert retry.closed
    assert capture_module.time.sleep.call_args_list == [call(0.01), call(0.01)]


def test_voice_retry_failure_rejects_short_initial_audio(harness, monkeypatch):
    first = FakeCapture([b"v" * 40])
    monkeypatch.setattr(capture_module, "AudioCapture", Mock(side_effect=[first, OSError("retry unavailable")]))
    monkeypatch.setattr(capture_module, "collect", Mock(return_value=b"s" * 100))
    assert harness._record_with_vad() == b""
    harness.logger.event.assert_any_call("service.capture.retry_error", error="retry unavailable")


@pytest.mark.parametrize(
    ("raw_size", "trimmed_size", "expected_size"),
    [(800, 400, 400), (800, 100, 800), (100, 80, 0), (800, 0, 800), (100, 0, 0)],
)
def test_voice_arecord_fallback_preserves_minimum_audio_policy(
    harness, monkeypatch, raw_size, trimmed_size, expected_size
):
    raw = b"r" * raw_size
    trimmed = b"t" * trimmed_size
    runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=raw, stderr=b""))
    monkeypatch.setattr(capture_module.subprocess, "run", runner)
    monkeypatch.setattr(capture_module, "collect", Mock(return_value=trimmed))
    expected = trimmed if expected_size == trimmed_size else raw[:expected_size]
    assert harness._record_with_arecord() == expected
    runner.assert_called_once()


@pytest.mark.parametrize("maximum_ms,duration", [(1000, "2"), (9000, "4")])
def test_voice_arecord_honors_device_channels_buffer_and_duration(harness, monkeypatch, maximum_ms, duration):
    harness._max_len = maximum_ms
    harness._capture_cfg.channels = 2
    harness._capture_cfg.device = "fake-device"
    harness._capture_cfg.buffer_seconds = 0.1
    runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=b"r" * 800, stderr=b""))
    monkeypatch.setattr(capture_module.subprocess, "run", runner)
    assert harness._record_with_arecord() == b"r" * 800
    args = runner.call_args.args[0]
    assert args[args.index("-D") + 1] == "fake-device"
    assert args[args.index("-c") + 1] == "2"
    assert args[args.index("-d") + 1] == duration
    assert args[args.index("--buffer-time") + 1] == "100000"


@pytest.mark.parametrize(
    ("result", "event"),
    [
        (SimpleNamespace(returncode=1, stdout=b"", stderr=b" failure "), "service.capture.arecord_failed"),
        (SimpleNamespace(returncode=0, stdout=b"", stderr=b""), "service.capture.arecord_empty"),
    ],
)
def test_voice_arecord_failure_or_empty_output_returns_no_audio(harness, monkeypatch, result, event):
    monkeypatch.setattr(capture_module.subprocess, "run", Mock(return_value=result))
    assert harness._record_with_arecord() == b""
    assert harness.logger.event.call_args.args[0] == event


def test_voice_missing_arecord_returns_no_audio(harness, monkeypatch):
    monkeypatch.setattr(capture_module.subprocess, "run", Mock(side_effect=FileNotFoundError))
    assert harness._record_with_arecord() == b""
    harness.logger.event.assert_called_with("service.capture.arecord_missing")


def test_voice_pcm_framing_omits_incomplete_trailing_frame(harness):
    assert list(harness._frames_from_pcm(b"abcdefghijkl", 5)) == [b"abcde", b"fghij"]
