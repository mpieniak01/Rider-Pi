"""Regression tests for VoiceService UI state publishing."""

from __future__ import annotations

import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

requests_stub = types.ModuleType("requests")


def _stub_post(*args, **kwargs):  # pragma: no cover - safety net
    raise RuntimeError("requests stub invoked")


requests_stub.post = _stub_post
requests_stub.RequestException = Exception
requests_stub.exceptions = types.SimpleNamespace(RequestException=Exception)
sys.modules.setdefault("requests", requests_stub)

from apps.voice.service import VoiceService


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
    }
    return VoiceService(config)


def test_once_publishes_idle_after_error(monkeypatch) -> None:
    service = _make_service()
    published_states: list[str] = []

    # Capture UI state publications.
    monkeypatch.setattr(service, "_publish_ui_state", published_states.append)

    def failing_cycle(*, speak: bool = True):
        published_states.append("listen")
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "_cycle", failing_cycle)

    assert service.once() is None
    assert published_states[:-1] == ["listen"]
    assert published_states[-1] == "idle"
