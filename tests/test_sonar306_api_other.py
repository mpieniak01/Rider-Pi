"""Packet 14 boundaries: inert HTTP, clock, file metadata and controller fixtures only."""

import base64
import copy
import json
import os
from types import SimpleNamespace

import pytest
from flask import Flask

from services.api_core import (
    chat_glue,
    chat_routes,
    face_anim,
    frames,
    navigation_state,
    playback_api,
    service_logs,
    system_sampling,
    voice_local_proxy,
)


@pytest.mark.parametrize("raw", ["", "0", "60001", "000001", "１２", "-1", "1.0", " 1"])
def test_playback_ttl_rejects_ambiguous_or_unbounded_values(raw):
    with pytest.raises(ValueError, match="playback_ttl_invalid"):
        playback_api._validate_ttl(raw)


@pytest.mark.parametrize("raw", ["1", "00001", "60000"])
def test_playback_ttl_keeps_accepted_ascii_boundaries(raw):
    playback_api._validate_ttl(raw)


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [(0, "frame_time_unknown"), (1000.2, "frame_clock_future"), (996, "frame_stale"), (999, None)],
)
def test_frame_file_provenance_never_becomes_capture_evidence(monkeypatch, tmp_path, stamp, expected):
    from services import camera_pipeline_store

    monkeypatch.setattr(camera_pipeline_store, "enabled", lambda: False)
    metadata = SimpleNamespace(st_mtime=stamp, st_size=7, st_mode=0o600 | 0o100000)
    row = frames.describe("raw", path=tmp_path / "fixture.jpg", now=1000, stat_result=metadata)
    assert row["error"] == expected
    assert row["observed_at"] is None
    assert row["capture_at"] is None
    assert row["provenance"] == "file_mtime"
    assert row["exists"] is True


def test_navigation_map_boundary_rejects_bool_dimensions_and_keeps_invalid_quality(monkeypatch):
    monkeypatch.setattr(navigation_state, "_rows", {"map": None, "pose": None, "path": None})
    monkeypatch.setattr(navigation_state.time, "time", lambda: 1000)
    base = {"observed_at": 1000, "width_cells": 1, "height_cells": 1, "grid": [0]}
    assert navigation_state.observe("mapper.map.data", dict(base, quality=None))
    assert navigation_state.snapshot()["map"]["quality"] is None
    assert not navigation_state.observe("mapper.map.data", dict(base, width_cells=True))
    row = navigation_state.snapshot()["map"]
    assert row["stale"] is True
    assert row["error"] == "invalid_navigation_data"
    assert row["observed_at"] == 1000


def test_cpu_counter_reset_does_not_invent_utilization_or_reset_summary_phase():
    clock = SimpleNamespace(now=100)
    counters = iter([(10, 100), (11, 104), (1, 2), (3, 10)])
    collected = []
    sampler = system_sampling.SystemSampler(
        lambda: next(counters),
        lambda slow: collected.append(slow) or {"mem": {"pct": 50}},
        clock=lambda: clock.now,
        wall_clock=lambda: clock.now + 1000,
    )
    sampler.sample()
    clock.now = 100.25
    sampler.sample()
    clock.now = 100.5
    sampler.sample()
    assert sampler.latest["cpu_pct"] is None
    clock.now = 101
    sampler.sample()
    assert sampler.latest["cpu_pct"] == 75
    assert sampler.summary_at == 101
    assert collected == [True, False]
    assert sampler.thread is None


def test_journal_stream_cap_is_shared_across_both_fixture_channels(monkeypatch):
    buffers = {"stdout": bytearray(b"123"), "stderr": bytearray(b"45")}
    selector = SimpleNamespace(unregister=lambda _: pytest.fail("Unexpected EOF"))
    monkeypatch.setattr(service_logs, "MAX_BYTES", 8)
    monkeypatch.setattr(os, "read", lambda _fd, _count: b"abcdef")
    ready = [(SimpleNamespace(fd=1, data="stderr"), 0)]
    assert service_logs._read_ready(selector, buffers, ready) is True
    assert buffers == {"stdout": bytearray(b"123"), "stderr": bytearray(b"45abc")}


def test_fallback_chat_keeps_options_limit_and_store_error_contract():
    app = Flask(__name__)
    calls = []
    store = SimpleNamespace(history=lambda n: calls.append(n) or [{"msg": "fixture"}])
    handlers = chat_routes._FallbackChat(store, lambda response: response)
    assert handlers._chat_history.__name__ == "_chat_history"
    assert handlers._chat_send.__name__ == "_chat_send"
    with app.test_request_context("/api/chat/history", method="OPTIONS"):
        response = handlers._chat_history()
        assert response.status_code == 204
        assert calls == []
    with app.test_request_context("/api/chat/history?limit=invalid"):
        response, code = handlers._chat_history()
        assert code == 200
        assert response.get_json()["items"] == [{"msg": "fixture"}]
        assert calls == [None]
    handlers.store = SimpleNamespace(append=lambda _: (_ for _ in ()).throw(ValueError("fixture")))
    with app.test_request_context("/api/chat/send", method="POST", json={"msg": "hello"}):
        response, code = handlers._chat_send()
        assert code == 500
        assert response.get_json()["error"] == "send_failed: fixture"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"ok": False, "reply": "plausible"}, "remote_backend_error"),
        ({"reply": "plausible", "source": " echo "}, "remote_demo_or_echo"),
        ({"reply": "plausible", "source": "real", "simulated": True}, "remote_demo_or_echo"),
        ({"choices": [{"message": {"content": ""}}], "source": "real"}, "remote_empty_reply"),
    ],
)
def test_remote_reply_rejection_provenance_is_preserved(payload, expected):
    assert chat_glue._payload_reply(payload) == (False, expected, "unavailable")


def test_remote_reply_candidate_priority_and_original_source_are_preserved():
    payload = {
        "source": " fixture ",
        "reply": " ",
        "text": " second ",
        "message": {"content": "third"},
        "choices": [{"message": {"content": "fourth"}}],
    }
    assert chat_glue._payload_reply(payload) == (True, "second", "fixture")


def test_face_close_always_attempts_controller_after_failed_sink(monkeypatch):
    state = copy.deepcopy(face_anim.STATE)
    monkeypatch.setattr(face_anim, "STATE", dict(state, playing=True, running=True))
    closed = []
    sink = SimpleNamespace(close=lambda: (_ for _ in ()).throw(RuntimeError("sink fixture")))
    controller = SimpleNamespace(close=lambda: closed.append("controller"))
    face_anim._Animator()._close_resources(sink, controller)
    assert closed == ["controller"]
    assert face_anim.STATE["error"] == "face_close_failed:sink fixture"
    assert face_anim.STATE["playing"] is False
    assert face_anim.STATE["running"] is False


def test_face_play_validates_before_stop_and_preserves_acquisition_order(monkeypatch):
    events = []
    settings = {"active_gestures": [], "style": "fixture", "idle": False, "power_mode": "battery"}
    monkeypatch.setattr(face_anim, "get_settings", lambda: events.append("settings") or settings)
    monkeypatch.setattr(face_anim, "stop", lambda _: events.append("stop"))
    monkeypatch.setattr(face_anim, "STATE", copy.deepcopy(face_anim.STATE))
    monkeypatch.setattr(face_anim, "descriptors", lambda: {"fps": {"battery": 12}})

    class Controller:
        def __init__(self, **_kwargs):
            events.append("controller")

        def configure(self, _settings):
            events.append("configure")

        def set_expr(self, _expr):
            events.append("expr")

        def close(self):
            events.append("close")

    monkeypatch.setattr(face_anim, "FaceController", Controller)
    monkeypatch.setattr(face_anim, "_make_sink", lambda: events.append("sink") or object())
    animator = SimpleNamespace(_thr=None, start=lambda: events.append("start"))
    monkeypatch.setattr(face_anim, "_anim", animator)
    rejected = face_anim.play({"expr": "invalid fixture"})
    assert rejected["status"] == 400
    assert events == []
    result = face_anim.play({"sink": "lcd"}, prepare_lcd=lambda: events.append("prepare"))
    assert result["ok"] is True
    assert events == ["settings", "stop", "settings", "controller", "configure", "expr", "prepare", "sink", "start"]


@pytest.mark.parametrize("ctype", ["application/json", "audio/wav", "audio/x-wav"])
def test_tts_response_keeps_audio_headers_without_playback(ctype):
    app = Flask(__name__)
    wav = b"inert fixture audio"
    body = (
        json.dumps({"status": "ok", "audio_b64": base64.b64encode(wav).decode()}).encode()
        if ctype == "application/json"
        else wav
    )
    with app.test_request_context("/api/voice/tts"):
        response = voice_local_proxy._tts_response(body, ctype)
        assert response.status_code == 200
        assert response.mimetype == "audio/wav"
        assert response.get_data() == wav
        assert response.headers["X-Voice-Proxy"] == "local"
        assert response.headers["Content-Disposition"] == "inline; filename=tts.wav"


@pytest.mark.parametrize(
    ("body", "expected"),
    [(b"{broken", "invalid json from voice-web"), (b'{"status":"no"}', "tts failed")],
)
def test_tts_backend_decode_errors_remain_502(body, expected):
    app = Flask(__name__)
    with app.test_request_context("/api/voice/tts"):
        response, code = voice_local_proxy._tts_response(body, "application/json")
        assert code == 502
        assert response.get_json()["error"] == expected


def test_tts_validation_keeps_explicit_disabled_backend_and_passthrough_boundary():
    assert voice_local_proxy._tts_payload({"text": "hello", "backend": "gemini"}) == (
        None,
        "Google/Gemini SDK integration is disabled",
    )
    assert voice_local_proxy._tts_payload({"text": " "}) == (None, "missing text")
    payload, error = voice_local_proxy._tts_payload({"text": " hello ", "provider": "local", "secret": "discard"})
    assert payload == {"text": "hello", "provider": "local"}
    assert error is None
