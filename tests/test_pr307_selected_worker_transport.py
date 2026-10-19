"""Selected local-worker confinement uses fake HTTP handlers; no network or SDK I/O."""

from __future__ import annotations

import json
import sys
import urllib.request
import urllib.response
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps import voice
from apps.voice import domain_worker
from services.api_core import chat_glue, text_profile

LOCAL_ENDPOINT = "http://127.0.0.1:8092/api/chat"


@pytest.fixture
def selected_profile(monkeypatch):
    status = {
        "stale": False,
        "pid": 42,
        "domains": ["chat"],
        "capabilities": {"chat": {"ready": True}},
        "chat_endpoint": LOCAL_ENDPOINT,
    }
    monkeypatch.setattr(text_profile, "requested_domains", lambda: {"chat"})
    monkeypatch.setattr(text_profile.task_runtime, "read_status", lambda _: status)
    monkeypatch.setattr(text_profile.systemd_ctrl, "status", lambda _: {"pid": 42, "active": "active"})
    return status


@pytest.mark.parametrize("host", ["192.0.2.7", "example.invalid", "2001:db8::1", "::1%lo", "[::1%lo]"])
def test_worker_rejects_non_loopback_or_scoped_bind(host, monkeypatch):
    monkeypatch.setattr(domain_worker, "worker_bind", lambda: (host, 8092))
    with pytest.raises(ValueError, match="requires_loopback_bind"):
        domain_worker._chat_endpoint()


@pytest.mark.parametrize("port", [0, -1, 65536, True, "8092"])
def test_worker_rejects_invalid_advertised_port(port, monkeypatch):
    monkeypatch.setattr(domain_worker, "worker_bind", lambda: ("127.0.0.1", port))
    with pytest.raises(ValueError, match="requires_loopback_bind"):
        domain_worker._chat_endpoint()


def _ready_chat(_domains):
    return {"ready": True, "missing": [], "capabilities": {"chat": {"ready": True}}}


def test_invalid_bind_writes_unready_profile_without_advertising_endpoint(monkeypatch):
    monkeypatch.setattr(domain_worker, "availability", _ready_chat)
    monkeypatch.setattr(domain_worker, "worker_bind", lambda: ("192.0.2.7", 8092))
    write = Mock()
    monkeypatch.setattr(domain_worker, "write_status", write)
    status = domain_worker.update_profile(SimpleNamespace(), {"chat"})
    assert status["ready"] is False
    assert status["capabilities"]["chat"]["ready"] is False
    assert status["missing"] == ["chat_worker_endpoint_requires_loopback_bind"]
    assert "chat_endpoint" not in status
    write.assert_called_once_with(status)


@pytest.mark.parametrize("check_only", [False, True])
def test_invalid_bind_is_reported_before_worker_start_or_passive_check(monkeypatch, capsys, check_only):
    monkeypatch.setattr(domain_worker, "availability", _ready_chat)
    monkeypatch.setattr(domain_worker, "requested_domains", lambda: {"chat"})
    monkeypatch.setattr(domain_worker, "worker_bind", lambda: ("192.0.2.7", 8092))
    monkeypatch.setattr(domain_worker, "write_status", Mock())
    monkeypatch.setattr(voice, "web", SimpleNamespace(), raising=False)
    monkeypatch.setattr(sys, "argv", ["domain-worker", "--check"] if check_only else ["domain-worker"])
    assert domain_worker.main() == 3
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["error"] == "voice_profile_unavailable"
    assert diagnostic["missing"] == ["chat_worker_endpoint_requires_loopback_bind"]


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://192.0.2.7:8092/api/chat",
        "http://example.invalid:8092/api/chat",
        "http://localhost:8092/api/chat",
        "http://[2001:db8::1]:8092/api/chat",
        "http://[::1%lo]:8092/api/chat",
        "http://user:secret@127.0.0.1:8092/api/chat",
        LOCAL_ENDPOINT + "?secret=token",
        LOCAL_ENDPOINT + "#fragment",
        LOCAL_ENDPOINT + ";params",
        "https://127.0.0.1:8092/api/chat",
        "http://127.0.0.1/api/chat",
        "http://127.0.0.1:0/api/chat",
        "http://127.0.0.1:65536/api/chat",
        "http://[malformed/api/chat",
        None,
    ],
)
def test_consumer_rejects_unconfined_endpoint_even_for_matching_local_pid(endpoint, selected_profile, caplog):
    selected_profile["chat_endpoint"] = endpoint
    assert text_profile.selected_endpoint() is None
    assert "Selected voice worker endpoint rejected" in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.parametrize("endpoint", [LOCAL_ENDPOINT, "http://127.0.0.2:8092/api/chat", "http://[::1]:8092/api/chat"])
def test_consumer_accepts_only_literal_loopback_with_explicit_port(endpoint, selected_profile):
    selected_profile["chat_endpoint"] = endpoint
    assert text_profile.selected_endpoint() == endpoint


def _fake_http_transport(monkeypatch, code=200):
    calls = []

    class FakeHTTPHandler(urllib.request.HTTPHandler):
        def http_open(self, req):
            calls.append((req.full_url, req.host, req.has_proxy(), json.loads(req.data)))
            headers = {"Content-Type": "application/json"}
            if code != 200:
                headers["Location"] = "http://203.0.113.7/redirected"
            response = urllib.response.addinfourl(
                BytesIO(b'{"ok":true,"text":"model reply"}'), headers, req.full_url, code
            )
            response.msg = "OK" if code == 200 else "Redirect"
            return response

    monkeypatch.setattr(urllib.request, "HTTPHandler", FakeHTTPHandler)
    return calls


def test_selected_worker_bypasses_proxy_environment_and_sends_only_to_loopback(monkeypatch, selected_profile):
    monkeypatch.delenv("CHAT_REMOTE_URL", raising=False)
    monkeypatch.setenv("http_proxy", "http://203.0.113.9:3128")
    monkeypatch.setenv("HTTP_PROXY", "http://203.0.113.10:3128")
    monkeypatch.setenv("ALL_PROXY", "http://203.0.113.11:3128")
    monkeypatch.setenv("NO_PROXY", "")
    getproxies = Mock(side_effect=AssertionError("internal transport must not read environment proxies"))
    monkeypatch.setattr(urllib.request, "getproxies", getproxies)
    calls = _fake_http_transport(monkeypatch)
    assert chat_glue._remote_reply("private prompt") == (True, "model reply", "remote")
    assert calls == [
        (
            LOCAL_ENDPOINT,
            "127.0.0.1:8092",
            False,
            {"text": "private prompt", "messages": [{"role": "user", "content": "private prompt"}]},
        )
    ]
    getproxies.assert_not_called()


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_selected_worker_redirect_cannot_send_prompt_to_another_host(code, monkeypatch, selected_profile):
    monkeypatch.delenv("CHAT_REMOTE_URL", raising=False)
    calls = _fake_http_transport(monkeypatch, code)
    ok, detail, source = chat_glue._remote_reply("private prompt")
    assert ok is False
    assert str(code) in detail
    assert source == "unavailable"
    assert len(calls) == 1
    assert calls[0][0] == LOCAL_ENDPOINT


def test_internal_transport_revalidates_before_creating_opener(monkeypatch):
    request = urllib.request.Request("http://example.invalid:8092/api/chat", data=b"private prompt")
    build = Mock(side_effect=AssertionError("invalid endpoint must not construct transport"))
    monkeypatch.setattr(urllib.request, "build_opener", build)
    with pytest.raises(ValueError, match="invalid_selected_worker_endpoint"):
        chat_glue._open_selected_worker(request, timeout=20)
    build.assert_not_called()


def test_explicit_remote_backend_keeps_its_existing_transport(monkeypatch):
    remote = "https://configured.invalid/api/chat"
    monkeypatch.setenv("CHAT_REMOTE_URL", remote)
    internal = Mock(side_effect=AssertionError("explicit backend must not use worker transport"))
    monkeypatch.setattr(chat_glue, "_open_selected_worker", internal)
    response = urllib.response.addinfourl(BytesIO(b'{"text":"configured reply"}'), {}, remote, 200)
    opened = Mock(return_value=response)
    monkeypatch.setattr(urllib.request, "urlopen", opened)
    assert chat_glue._remote_reply("operator prompt") == (True, "configured reply", "remote")
    assert opened.call_args.args[0].full_url == remote
    assert opened.call_args.kwargs == {"timeout": 20}
    internal.assert_not_called()
