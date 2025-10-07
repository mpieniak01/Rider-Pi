"""Tests for default PTT behaviour in streaming voice service."""

from __future__ import annotations

import contextlib

import pytest

from apps.voice.svc_stream import StreamingVoiceService


@pytest.fixture
def base_config() -> dict[str, object]:
    """Return minimal streaming configuration without explicit hotword section."""

    return {
        "stream": {"endpoint": "ws://test", "auth": "dummy"},
        "capture": {"sample_rate": 16000, "channels": 1},
        "playback": {},
        "service": {"turn": {"commit_on_key": True}},
    }


def _cleanup(service: StreamingVoiceService) -> None:
    """Ensure threads/events are stopped after each test."""

    with contextlib.suppress(Exception):
        service.stop()


def test_ptt_enabled_by_default(base_config):
    """PTT should auto-enable when configuration omits explicit hotword settings."""

    service = StreamingVoiceService(base_config)
    try:
        assert service.ptt_enabled is True
        assert service.ptt_controller.ptt_enabled is True
        assert service.audio_transmitter.ptt_enabled is True
    finally:
        _cleanup(service)


def test_ptt_disabled_when_service_hotword_disabled(base_config):
    """Explicitly disabling hotword should turn off PTT even with commit_on_key."""

    cfg = dict(base_config)
    cfg_service = dict(cfg.get("service", {}))
    cfg_service.update({"hotword_enabled": False})
    cfg["service"] = cfg_service

    service = StreamingVoiceService(cfg)
    try:
        assert service.ptt_enabled is False
        assert service.ptt_controller.ptt_enabled is False
        assert service.audio_transmitter.ptt_enabled is False
    finally:
        _cleanup(service)

