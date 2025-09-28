from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.hardware


import copy
import pathlib
import sys
import types
from dataclasses import dataclass

import pytest

from apps.voice.service import VoiceService

"""
Regression tests for VoiceService UI state publishing.

Kluczowe: patchujemy **apps.voice.service_impl.*** (a nie asr/tts/playback bezpośrednio),
bo service_impl importuje symbole przy ładowaniu:
    from ..asr import transcribe
    from ..tts import synthesize
    from ..playback import play_bytes
i potem używa lokalnych nazw modułu (service_impl.transcribe itd.).
"""

# Ścieżka projektu na początek sys.path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# Minimalny stub requests (bez sieci)
requests_stub = types.ModuleType("requests")


def _stub_post(*_args, **_kwargs):  # pragma: no cover
    raise RuntimeError("requests stub invoked")


requests_stub.post = _stub_post
requests_stub.RequestException = Exception
requests_stub.exceptions = types.SimpleNamespace(RequestException=Exception)
sys.modules.setdefault("requests", requests_stub)


# Lokalne Transcript (żeby test nie musiał importować z apps.voice.asr)
@dataclass
class Transcript:
    text: str
    language: str | None = None


class FakePublisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []

    def publish(self, topic: str, payload: dict, add_ts: bool = False) -> None:  # noqa: ARG002
        self.messages.append((topic, dict(payload)))

    def send(self, topic: str, payload: dict) -> None:  # pragma: no cover
        self.publish(topic, payload)


_BASE_CONFIG = {
    "chat": {"backend": "echo", "model": "dummy", "system_prompt": "", "max_history": 1},
    "nlu": {"chat_threshold": 0.0, "command_keywords": {}, "llm_model": "dummy"},
    "capture": {
        "backend": "pulse",
        "device": None,
        "sample_rate": 16000,
        "channels": 1,
        "frame_ms": 20,
        "buffer_seconds": 1,
        "command": None,
    },
    "asr": {"backend": "dummy", "model": "dummy", "language": "en"},
    "tts": {"backend": "dummy", "model": "dummy", "voice": "dummy", "format": "wav"},
    "playback": {"backend": "pulse", "alsa_device": None, "volume": 100, "ding": {"enabled": False}},
    "hotword": {
        "enabled": False,
        "engine": "off",
        "model": None,
        "sensitivity": 0.5,
        "auto_gain": 1.0,
        "threshold": 0.5,
    },
    "vad": {"mode": 3, "frame_ms": 30, "tail_ms": 350, "max_len_ms": 4500, "energy_gate_dbfs": -36.0},
    "service": {"save_audio": False, "recordings_dir": "data/recordings"},
    "logging": {"level": "INFO"},
}


def _base_config() -> dict:
    return copy.deepcopy(_BASE_CONFIG)


@pytest.fixture()
def service_impl_mod():
    import importlib

    return importlib.import_module("apps.voice.service_impl")


def _state_sequence(publisher: FakePublisher) -> list[str]:
    return [payload["state"] for topic, payload in publisher.messages if topic == "ui.state"]


def _patch_runtime(monkeypatch: pytest.MonkeyPatch, service_impl_mod, *, transcribe_text: str):
    """
    Patchujemy WSZYSTKO, czego _cycle() dotyka poza VoiceService:
      - service_impl.transcribe -> Transcript(transcribe_text)
      - service_impl.time.sleep -> no-op
      - service_impl.synthesize -> (b"audio", 16000, "wav")
      - service_impl.play_bytes -> no-op
    """
    monkeypatch.setattr(service_impl_mod, "transcribe", lambda *a, **k: Transcript(text=transcribe_text, language="en"))
    monkeypatch.setattr(service_impl_mod.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(service_impl_mod, "synthesize", lambda *a, **k: (b"audio", 16000, "wav"), raising=False)
    monkeypatch.setattr(service_impl_mod, "play_bytes", lambda *a, **k: None, raising=False)


def _skip_if_no_device_env():
    if os.environ.get('RUN_DEVICE_TESTS') != '1':
        pytest.skip('Hardware/ALSA tests disabled on CI (set RUN_DEVICE_TESTS=1 to enable).')


def test_once_publishes_idle_after_error(monkeypatch: pytest.MonkeyPatch, service_impl_mod) -> None:
    service = VoiceService(_base_config(), ui_publisher=FakePublisher())
    published_states: list[str] = []
    monkeypatch.setattr(service, "_publish_ui_state", published_states.append)

    def failing_cycle(*, speak: bool = True):  # noqa: ARG001
        published_states.append("listen")
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "_cycle", failing_cycle)
    assert service.once() is None
    assert published_states[:-1] == ["listen"]
    assert published_states[-1] == "idle"


def test_cycle_emits_idle_when_reply_empty(monkeypatch: pytest.MonkeyPatch, service_impl_mod) -> None:
    _patch_runtime(monkeypatch, service_impl_mod, transcribe_text="ok")  # ASR OK, ale odpowiedź będzie pusta
    config = _base_config()
    config.setdefault("service", {}).update({"min_capture_ms": 0})
    publisher = FakePublisher()
    service = VoiceService(config, ui_publisher=publisher)

    monkeypatch.setattr(service, "_record_with_vad", lambda: b"\x00\x01" * 10)
    monkeypatch.setattr(service, "_wait_hotword_without_capture", lambda: True)
    monkeypatch.setattr(service, "_handle_intent", lambda intent: "   ")  # pusta odpowiedź

    result = service._cycle()

    states = _state_sequence(publisher)
    states = states[1:] if (states and states[0] == "idle") else states
    assert states == ["hearing", "thinking", "idle"]
    assert result.audio is None and result.audio_format == "" and result.sample_rate == 0


def test_cycle_idle_after_short_recording(monkeypatch: pytest.MonkeyPatch, service_impl_mod) -> None:
    _patch_runtime(monkeypatch, service_impl_mod, transcribe_text="ignored")
    config = _base_config()
    publisher = FakePublisher()
    service = VoiceService(config, ui_publisher=publisher)

    monkeypatch.setattr(service, "_record_with_vad", lambda: b"")  # za krótko
    monkeypatch.setattr(service, "_wait_hotword_without_capture", lambda: True)

    with pytest.raises(RuntimeError):
        service._cycle()

    states = _state_sequence(publisher)
    assert states[-2:] == ["hearing", "idle"], states


def test_listen_resets_state_after_cycle_error(monkeypatch: pytest.MonkeyPatch, service_impl_mod) -> None:
    _patch_runtime(monkeypatch, service_impl_mod, transcribe_text="ignored")
    config = _base_config()
    publisher = FakePublisher()
    service = VoiceService(config, ui_publisher=publisher)

    class OneShotEvent:
        def __init__(self) -> None:
            self.calls = 0

        def is_set(self) -> bool:
            self.calls += 1
            return self.calls >= 2

        def set(self) -> None:  # pragma: no cover
            self.calls = 2

    service.stop_event = OneShotEvent()

    def failing_cycle(*args, **kwargs):  # noqa: ANN001
        service._publish_ui_state("hearing")
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "_cycle", failing_cycle)
    service.listen()

    states = _state_sequence(publisher)
    assert states[-2:] == ["hearing", "idle"], states


def test_vad_state_reset_between_cycles(monkeypatch: pytest.MonkeyPatch, service_impl_mod) -> None:
    """VAD reset powinien następować między kolejnymi cyklami."""
    _patch_runtime(monkeypatch, service_impl_mod, transcribe_text="test")

    config = _base_config()
    config.setdefault("service", {}).update({"min_capture_ms": 0})
    publisher = FakePublisher()
    service = VoiceService(config, ui_publisher=publisher)

    reset_calls: list[bool] = []
    original_reset = service._vad.reset

    def track_reset():
        reset_calls.append(True)
        return original_reset()

    monkeypatch.setattr(service._vad, "reset", track_reset)

    monkeypatch.setattr(service, "_record_with_vad", lambda: b"\x00\x01" * 100)
    monkeypatch.setattr(service, "_wait_hotword_without_capture", lambda: True)
    monkeypatch.setattr(service, "_handle_intent", lambda intent: "Test response")

    service._cycle()
    service._cycle()

    assert len(reset_calls) == 2, f"Expected 2 VAD reset calls, got {len(reset_calls)}"
