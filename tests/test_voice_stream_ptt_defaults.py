"""Tests for default PTT behaviour in streaming voice service."""

from __future__ import annotations

import pytest
import pytest_asyncio

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


@pytest_asyncio.fixture
async def service_factory(base_config):
    """Factory fixture for creating services with proper cleanup."""
    services = []

    def _create_service(config=None):
        cfg = config if config is not None else base_config
        svc = StreamingVoiceService(cfg)
        services.append(svc)
        return svc

    yield _create_service

    # Clean up all created services
    for svc in services:
        try:
            await svc.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_ptt_enabled_by_default(base_config):
    """PTT should auto-enable when configuration omits explicit hotword settings."""

    service = StreamingVoiceService(base_config)
    try:
        assert service.ptt_enabled is True
        assert service.ptt_controller.ptt_enabled is True
        assert service.audio_transmitter.ptt_enabled is True
    finally:
        try:
            await service.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_ptt_disabled_when_service_hotword_disabled(base_config):
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
        try:
            await service.close()
        except Exception:
            pass
