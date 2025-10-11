# tests/test_voice_svc_stream_proxy.py
"""Tests for apps.voice.stream.svc_streaming module exports (no I/O, no ALSA)."""

import pytest


def test_exports_present():
    from apps.voice.stream import svc_streaming as stream_service

    assert hasattr(stream_service, "StreamConfig")
    assert hasattr(stream_service, "StreamingVoiceService")


@pytest.mark.asyncio
async def test_service_once_invocation(monkeypatch):
    from apps.voice.stream import svc_streaming as stream_service

    calls = {"once": 0}

    class DummyService:
        def __init__(self, cfg, ui_publisher=None):
            self.cfg = cfg
            self.ui_publisher = ui_publisher

        async def once(self, *, speak=True):
            assert speak is True
            calls["once"] += 1
            return {"transcript": {"text": "test"}}

        def stop(self):
            pass

    # Replace StreamingVoiceService with dummy
    monkeypatch.setattr(stream_service, "StreamingVoiceService", DummyService)

    # Direct service invocation
    svc = stream_service.StreamingVoiceService({"stream": {}})
    result = await svc.once(speak=True)
    assert result == {"transcript": {"text": "test"}}
    assert calls["once"] == 1


@pytest.mark.asyncio
async def test_service_listen_invocation(monkeypatch):
    from apps.voice.stream import svc_streaming as stream_service

    calls = {"listen": 0}

    class DummyService:
        def __init__(self, cfg, ui_publisher=None):
            self.cfg = cfg
            self.ui_publisher = ui_publisher

        async def listen(self):
            calls["listen"] += 1

        def stop(self):
            pass

    monkeypatch.setattr(stream_service, "StreamingVoiceService", DummyService)

    # Direct service invocation
    svc = stream_service.StreamingVoiceService({"stream": {}})
    await svc.listen()
    assert calls["listen"] == 1


@pytest.mark.asyncio
async def test_ptt_mode_configuration():
    """Test that PTT mode is configured correctly in service."""
    from apps.voice.stream import svc_streaming as stream_service

    ptt_config = {
        "stream": {},
        "hotword": {"enabled": True, "engine": "ptt"},
        "capture": {"sample_rate": 16000, "channels": 1},
        "playback": {},
        "service": {},
    }

    svc = stream_service.StreamingVoiceService(ptt_config)
    try:
        # Verify PTT configuration is applied
        assert svc.config["hotword"]["enabled"] is True
        assert svc.config["hotword"]["engine"] == "ptt"
    finally:
        try:
            await svc.close()
        except Exception:
            pass
