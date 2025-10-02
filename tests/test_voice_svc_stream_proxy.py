# tests/test_voice_svc_stream_proxy.py
"""Proxy tests for apps.voice.svc_stream (no I/O, no ALSA)."""

import pytest


def test_exports_present():
    from apps.voice import svc_stream

    assert hasattr(svc_stream, "StreamConfig")
    assert hasattr(svc_stream, "StreamingVoiceService")
    assert hasattr(svc_stream, "run_once_stream")
    assert hasattr(svc_stream, "run_listen_stream")
    assert hasattr(svc_stream, "run_ptt_stream")


@pytest.mark.asyncio
async def test_run_once_stream_invokes_service_once(monkeypatch):
    from apps.voice import svc_stream

    calls = {"once": 0}

    class DummyService:
        def __init__(self, cfg, ui_publisher=None):
            self.cfg = cfg
            self.ui_publisher = ui_publisher

        async def once(self, *, speak=True):
            assert speak is True
            calls["once"] += 1

    # Zamieniamy StreamingVoiceService tylko w module proxy
    monkeypatch.setattr(svc_stream, "StreamingVoiceService", DummyService)

    # Uruchamiamy wrapper (użyje asyncio.run wewnątrz)
    rc = svc_stream.run_once_stream({"stream": {}}, args=None)
    assert rc == 0
    assert calls["once"] == 1


@pytest.mark.asyncio
async def test_run_listen_stream_invokes_service_listen(monkeypatch):
    from apps.voice import svc_stream

    calls = {"listen": 0}

    class DummyService:
        def __init__(self, cfg, ui_publisher=None):
            self.cfg = cfg
            self.ui_publisher = ui_publisher

        async def listen(self):
            calls["listen"] += 1

    monkeypatch.setattr(svc_stream, "StreamingVoiceService", DummyService)
    rc = svc_stream.run_listen_stream({"stream": {}}, args=None)
    assert rc == 0
    assert calls["listen"] == 1


def test_run_ptt_stream_sets_hotword_and_delegates(monkeypatch):
    from apps.voice import svc_stream

    captured = {}

    def fake_run_listen_stream(cfg, args):
        captured["cfg"] = cfg
        return 0

    monkeypatch.setattr(svc_stream, "run_listen_stream", fake_run_listen_stream)

    base_cfg = {"stream": {}, "hotword": {"enabled": False}}
    rc = svc_stream.run_ptt_stream(base_cfg, args=None)
    assert rc == 0

    cfg = captured["cfg"]
    assert cfg["hotword"]["enabled"] is True
    assert cfg["hotword"]["engine"] == "ptt"
