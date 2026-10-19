"""Callback and fallback contracts without services, network or audio I/O."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, call

import pytest
from flask import Flask

from apps.voice import svc_file
from apps.voice.stream import svc_streaming
from services.api_core import chat_glue, home_auth_route
from services.core.features import NullPublisher


@pytest.mark.parametrize("method", ["GET", "OPTIONS"])
def test_auth_url_callback_keeps_positional_injected_logger_and_preflight(monkeypatch, method):
    app = Flask(__name__)
    preview = Mock(return_value={"ok": True, "auth_url": "fixture-url", "port": 1234})
    logger = Mock()
    cors_calls = []

    def corsify(response):
        cors_calls.append(response)
        response.headers["X-Fixture-Cors"] = "applied"
        return response

    monkeypatch.setattr(home_auth_route, "build_auth_url_preview", preview)
    with app.test_request_context("/api/home/auth/url", method=method):
        response = app.make_response(home_auth_route.home_auth_url(corsify=corsify, logger=logger))

    assert response.headers["X-Fixture-Cors"] == "applied"
    assert len(cors_calls) == 1
    assert logger.mock_calls == []
    if method == "OPTIONS":
        assert response.status_code == 204
        assert response.get_data() == b""
        preview.assert_not_called()
    else:
        assert response.status_code == 200
        assert response.get_json() == {"ok": True, "auth_url": "fixture-url", "port": 1234}
        preview.assert_called_once_with()


def test_auth_url_failed_preview_preserves_error_and_cors_without_logging(monkeypatch):
    app = Flask(__name__)
    logger = Mock()
    monkeypatch.setattr(home_auth_route, "build_auth_url_preview", lambda: {"ok": False, "error": "not_configured"})
    with app.test_request_context("/api/home/auth/url"):
        response = app.make_response(home_auth_route.home_auth_url(lambda value: value, logger))

    assert response.status_code == 400
    assert response.get_json() == {"ok": False, "error": "not_configured"}
    assert logger.mock_calls == []


@pytest.mark.parametrize("available", [False, True])
def test_retired_local_callback_keeps_remote_fallback_and_failure_evidence(monkeypatch, available):
    from services import compute_config

    app = Flask(__name__)
    history = []
    remote = Mock(
        return_value=(True, "fixture answer", "fixture-backend") if available else (False, "offline", "unavailable")
    )
    monkeypatch.setattr(compute_config, "selected_executor", lambda: None)
    monkeypatch.setattr(chat_glue, "_store_add", history.append)
    monkeypatch.setattr(chat_glue, "_remote_reply", remote)
    with app.test_request_context(
        "/api/chat/send", method="POST", json={"text": "  fixture prompt  ", "user": "reader"}
    ):
        response = app.make_response(chat_glue.chat_send())

    body = response.get_json()
    remote.assert_called_once_with("fixture prompt")
    assert history[0] == {"user": "reader", "msg": "fixture prompt"}
    assert body["ok"] is available
    if available:
        assert response.status_code == 200
        assert body["reply"] == "fixture answer"
        assert body["source"] == "fixture-backend"
        assert body["error"] is None
        assert history[1] == {"user": "bot", "msg": "fixture answer", "source": "fixture-backend"}
    else:
        assert response.status_code == 503
        assert body["reply"] == "fixture prompt"
        assert body["source"] == "echo"
        assert body["error"] == "ai_backend_unavailable"
        assert body["backend_error"] == "offline"
        assert history[1] == {"user": "bot", "msg": "fixture prompt", "source": "echo"}


@pytest.mark.parametrize("add_ts", [False, True])
def test_null_publisher_accepts_named_transport_option_and_records_a_payload_snapshot(add_ts):
    publisher = NullPublisher()
    payload = {"mode": "fixture", "ts": 123}
    result = publisher.publish(topic="tracking.mode:set", payload=payload, add_ts=add_ts)
    payload["mode"] = "changed after publish"

    assert result is None
    assert publisher.sent == [("tracking.mode:set", {"mode": "fixture", "ts": 123})]


@pytest.mark.parametrize("text", ["", "   "])
def test_file_speech_queue_rejects_blank_text_before_enqueueing(text):
    service = object.__new__(svc_file.VoiceService)
    service._speech_queue = Mock()

    result = service._request_speech(text, source="chat")

    assert result is None
    service._speech_queue.put.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["once", "listen"])
async def test_public_stream_coroutine_stops_before_session_on_sync_transport_configuration_failure(monkeypatch, mode):
    service = object.__new__(svc_streaming.StreamingVoiceService)
    service.logger = Mock()
    service._get_auth_header = Mock(side_effect=RuntimeError("fixture auth unavailable"))
    service._publish_ui_state = Mock()
    service._send_session_init = AsyncMock()
    service._run_with_reconnect = AsyncMock()
    service._cleanup = AsyncMock()
    construct = Mock()
    monkeypatch.setattr(svc_streaming, "ReconnectingTransport", construct)

    result = await getattr(service, mode)()

    assert result is None
    assert service.logger.event.call_args_list == [
        call(f"stream.{mode}.start"),
        call("transport.init.error", error="fixture auth unavailable"),
    ]
    construct.assert_not_called()
    service._send_session_init.assert_not_awaited()
    service._run_with_reconnect.assert_not_awaited()
    service._cleanup.assert_not_awaited()
    if mode == "listen":
        service._publish_ui_state.assert_called_once_with("idle")
    else:
        service._publish_ui_state.assert_not_called()
