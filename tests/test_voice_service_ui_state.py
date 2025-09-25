from __future__ import annotations

import copy
import pathlib
import sys
import types
from dataclasses import dataclass

import pytest

from apps.voice.service import VoiceService

"""
Regression tests for VoiceService UI state publishing.

Kluczowe poprawki:
- patchujemy apps.voice.asr.transcribe (a nie fasadę), żeby nie dzwonić do OpenAI.
- patchujemy apps.voice.service_impl.time.sleep (tam używany jest time.sleep).
"""

# Ścieżka projektu
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# Minimalny stub requests (bez sieci)
requests_stub = types.ModuleType("requests")


def _stub_post(*_args, **_kwargs):  # pragma: no cover
    raise RuntimeError("requests stub invoked")


requests_stub.post = _stub_post
requests_stub.RequestException = Exception
requests_stub.exceptions = types.SimpleNamespace(RequestException=Exception)
sys.modules.setdefault("requests", requests_stub)


# Lokalne Transcript (żeby nie importować apps.voice.asr i OpenAI)
@dataclass
class Transcript:
    text: str
    language: str | None = None


def _make_service() -> VoiceService:
    config = {
        "capture": {},
        "vad": {},
        "hotword": {"enabled": False, "engine": "off"},
        "asr": {
            "backend": "dummy",
            "model": "test",
            "language": "en",
            "temperature": 0.0,
            "prompt": None,
            "vosk_model_dir": "",
            "whisper_model": "tiny",
            "input_encoding": "s16le",
        },
        "nlu": {
            "chat_threshold": 0.5,
            "command_keywords": {},
            "llm_model": "dummy",
        },
        "chat": {
            "backend": "echo",
            "model": "dummy",
            "system_prompt": "prompt",
            "max_history": 1,
        },
        "tts": {
            "backend": "dummy",
            "voice": "dummy",
            "model": "dummy",
            "format": "wav",
            "piper_model": None,
            "piper_config": None,
        },
        "playback": {
            "backend": "dummy",
            "alsa_device": "default",
            "volume": 0,
            "ding": {"enabled": False, "path": "", "gain_db": 0.0},
        },
        "service": {
            "save_audio": False,
            "recordings_dir": "data/recordings",
            "history_size": 1,
        },
        "logging": {"level": "INFO"},
    }
    return VoiceService(config)


def test_once_publishes_idle_after_error(monkeypatch) -> None:
    service = _make_service()
    published_states: list[str] = []

    # Przechwyt publikacji stanu UI
    monkeypatch.setattr(service, "_publish_ui_state", published_states.append)

    def failing_cycle(*, speak: bool = True):  # noqa: ARG001
        published_states.append("listen")
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "_cycle", failing_cycle)

    assert service.once() is None
    assert published_states[:-1] == ["listen"]
    assert published_states[-1] == "idle"


class _RequestsStub:
    RequestException = Exception

    @staticmethod
    def post(*_args, **_kwargs):  # pragma: no cover
        class _Resp:
            status_code = 200
            headers = {}
            content = b""
            text = ""

            def json(self):  # pragma: no cover
                return {}

        return _Resp()


sys.modules.setdefault("requests", _RequestsStub())


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
def voice_module():
    import apps.voice.service as voice_service_module

    return voice_service_module


def _state_sequence(publisher: FakePublisher) -> list[str]:
    return [payload["state"] for topic, payload in publisher.messages if topic == "ui.state"]


def test_cycle_emits_idle_when_reply_empty(monkeypatch: pytest.MonkeyPatch, voice_module) -> None:
    # Patchujemy właściwe moduły
    import importlib

    asr_mod = importlib.import_module("apps.voice.asr")
    monkeypatch.setattr(asr_mod, "transcribe", lambda *_, **__: Transcript(text="ok", language="en"))

    service_impl = importlib.import_module("apps.voice.service_impl")
    monkeypatch.setattr(service_impl.time, "sleep", lambda *_a, **_k: None)

    config = _base_config()
    config.setdefault("service", {}).update({"min_capture_ms": 0})
    publisher = FakePublisher()
    service = VoiceService(config, ui_publisher=publisher)

    monkeypatch.setattr(service, "_record_with_vad", lambda: b"\x00\x01" * 10)
    monkeypatch.setattr(service, "_wait_hotword_without_capture", lambda: True)
    monkeypatch.setattr(service, "_handle_intent", lambda intent: "   ")

    # Tłumimy TTS/playback defensywnie
    monkeypatch.setattr(voice_module, "synthesize", lambda *a, **k: (b"audio", 16000, "wav"), raising=False)
    monkeypatch.setattr(voice_module, "play_bytes", lambda *a, **k: None, raising=False)

    result = service._cycle()

    states = _state_sequence(publisher)
    states = states[1:] if (states and states[0] == "idle") else states
    assert states == ["hearing", "thinking", "idle"]
    assert result.audio is None
    assert result.audio_format == ""
    assert result.sample_rate == 0


def test_cycle_idle_after_short_recording(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    service_impl = importlib.import_module("apps.voice.service_impl")
    monkeypatch.setattr(service_impl.time, "sleep", lambda *_a, **_k: None)

    config = _base_config()
    publisher = FakePublisher()
    service = VoiceService(config, ui_publisher=publisher)

    monkeypatch.setattr(service, "_record_with_vad", lambda: b"")
    monkeypatch.setattr(service, "_wait_hotword_without_capture", lambda: True)

    with pytest.raises(RuntimeError):
        service._cycle()

    states = _state_sequence(publisher)
    assert states[-2:] == ["hearing", "idle"], states


def test_listen_resets_state_after_cycle_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    service_impl = importlib.import_module("apps.voice.service_impl")
    monkeypatch.setattr(service_impl.time, "sleep", lambda *_a, **_k: None)

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


def test_vad_state_reset_between_cycles(monkeypatch: pytest.MonkeyPatch) -> None:
    """VAD reset powinien następować między kolejnymi cyklami."""
    import importlib

    asr_mod = importlib.import_module("apps.voice.asr")
    monkeypatch.setattr(asr_mod, "transcribe", lambda *_, **__: Transcript(text="test", language="en"))
    service_impl = importlib.import_module("apps.voice.service_impl")
    monkeypatch.setattr(service_impl.time, "sleep", lambda *_a, **_k: None)

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

    # Tłumimy TTS/playback
    monkeypatch.setattr(
        sys.modules.get("apps.voice.service"), "synthesize", lambda *a, **k: (b"audio", 16000, "wav"), raising=False
    )
    monkeypatch.setattr(sys.modules.get("apps.voice.service"), "play_bytes", lambda *a, **k: None, raising=False)

    service._cycle()
    service._cycle()

    assert len(reset_calls) == 2, f"Expected 2 VAD reset calls, got {len(reset_calls)}"
