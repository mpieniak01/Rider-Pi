"""Vision transport uses loopback fixtures only; never robot or actuator APIs."""

import json
import socket
import threading
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from apps.compute import navigation_transport as module
from apps.compute.client import ComputeError


@pytest.fixture
def server():
    replies, received = deque(), []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.client_address, self.path, body, self.headers.get("Authorization")))
            code, payload = replies.popleft() if replies else (200, b'{"action":"stop"}')
            self.send_response(code)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Content-Type", "application/json")
            if code == 302:
                self.send_header("Location", "/forbidden")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_):
            pass

    instance = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=instance.serve_forever, daemon=True)
    worker.start()
    base = "http://127.0.0.1:" + str(instance.server_port)
    try:
        yield base, replies, received
    finally:
        instance.shutdown()
        instance.server_close()
        worker.join(1)


def request(base, *, path="decision", payload=b"frame"):
    return urllib.request.Request(
        base + module.PREFIX + path,
        data=payload,
        headers={"Authorization": "Bearer fixture-only", "Content-Type": "image/jpeg"},
    )


def test_consecutive_frames_share_one_real_http_connection(server):
    base, _, received = server
    transport = module.NavigationHTTPTransport(base)
    try:
        for index in range(4):
            with transport.open(request(base, payload=str(index).encode()), timeout=0.3) as response:
                assert json.load(response) == {"action": "stop"}
        assert len({row[0] for row in received}) == 1
        assert [row[2] for row in received] == [b"0", b"1", b"2", b"3"]
        assert transport.status() == {"connections": 1, "requests": 4}
    finally:
        transport.close()
    assert transport.connection is None
    with pytest.raises(ComputeError, match="navigation_transport_closed"):
        transport.open(request(base), timeout=0.3)


def test_http_error_is_not_replayed_and_next_capture_can_use_connection(server):
    base, replies, received = server
    replies.append((429, b'{"detail":{"code":"vision_busy"}}'))
    transport = module.NavigationHTTPTransport(base)
    try:
        with pytest.raises(urllib.error.HTTPError) as caught:
            transport.open(request(base), timeout=0.3)
        assert caught.value.code == 429
        assert json.load(caught.value)["detail"]["code"] == "vision_busy"
        assert len(received) == 1
        transport.open(request(base, path="decision-reference", payload=b"next-source"), timeout=0.3)
        assert len(received) == 2 and received[-1][1].endswith("decision-reference")
        assert transport.connections == 1
    finally:
        transport.close()


@pytest.mark.parametrize(
    "code,payload,error",
    [
        (302, b"", "navigation_redirect_denied"),
        (200, b"x" * 16385, "navigation_response_bounds"),
    ],
)
def test_redirect_and_oversized_body_close_without_replay(server, code, payload, error):
    base, replies, received = server
    replies.append((code, payload))
    transport = module.NavigationHTTPTransport(base)
    with pytest.raises(ComputeError, match=error):
        transport.open(request(base), timeout=0.3)
    assert len(received) == 1 and transport.connection is None
    assert all(row[1] != "/forbidden" for row in received)
    transport.close()


def test_idle_connection_is_replaced_before_new_capture(server):
    base, _, received = server
    now = [1.0]
    transport = module.NavigationHTTPTransport(base, clock=lambda: now[0])
    try:
        transport.open(request(base), timeout=0.3)
        now[0] += 2.0
        transport.open(request(base), timeout=0.3)
        assert transport.connections == 2 and received[0][0] != received[1][0]
    finally:
        transport.close()


@pytest.mark.parametrize(
    "error", [TimeoutError(), socket.timeout(), OSError(), module.http.client.RemoteDisconnected()]
)
def test_connection_failure_is_once_only_and_discards_socket(monkeypatch, error):
    calls = []
    connection = SimpleNamespace(
        sock=None,
        request=lambda *a, **kw: calls.append("request"),
        getresponse=lambda: (_ for _ in ()).throw(error),
        close=lambda: calls.append("close"),
    )
    monkeypatch.setattr(module.http.client, "HTTPConnection", lambda *a, **kw: connection)
    transport = module.NavigationHTTPTransport("http://127.0.0.1")
    with pytest.raises((TimeoutError, urllib.error.URLError)):
        transport.open(request("http://127.0.0.1"), timeout=0.15)
    assert calls == ["request", "close"] and transport.connection is None
    assert connection.timeout == 0.15
    transport.close()


@pytest.mark.parametrize("target", ["http://localhost", "https://127.0.0.1", "http://127.0.0.1:81"])
def test_credentials_cannot_be_sent_to_a_different_origin(target):
    transport = module.NavigationHTTPTransport("http://127.0.0.1")
    with pytest.raises(ComputeError, match="navigation_transport_target_invalid"):
        transport.open(request(target), timeout=0.3)
    assert transport.requests == 0 and transport.connection is None
    transport.close()
