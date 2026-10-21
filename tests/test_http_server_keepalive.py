"""Real-wire dummy WSGI only; no API bootstrap, robot, camera or actuators."""

import http.client
import json
import socket
import threading
from importlib import metadata
from types import SimpleNamespace

import pytest
from werkzeug.serving import make_server

from services.api_core import http_server as module


@pytest.mark.parametrize("flag", [None, "", "0", "false", "off"])
def test_default_does_not_select_a_handler_or_check_runtime(monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv(module.FLAG, raising=False)
    else:
        monkeypatch.setenv(module.FLAG, flag)
    monkeypatch.setattr(module, "qualified_runtime", lambda: pytest.fail("default must not alter runtime"))
    assert module.server_options() == {}


@pytest.mark.parametrize("flag", ["1", "true", "on", " TRUE "])
def test_explicit_optin_requires_the_qualified_runtime(monkeypatch, flag):
    monkeypatch.setenv(module.FLAG, flag)
    monkeypatch.setattr(module, "qualified_runtime", lambda: False)
    with pytest.raises(RuntimeError, match="^http_keepalive_runtime_unsupported$"):
        module.server_options()
    monkeypatch.setattr(module, "qualified_runtime", lambda: True)
    assert module.server_options() == {"request_handler": module.PassiveReadRequestHandler}


@pytest.mark.parametrize("flag", ["auto", "yes", "2"])
def test_invalid_flag_fails_closed(monkeypatch, flag):
    monkeypatch.setenv(module.FLAG, flag)
    with pytest.raises(RuntimeError, match="^http_keepalive_flag_invalid$"):
        module.server_options()


@pytest.mark.parametrize(
    "python,werkzeug,expected", [((3, 9), "1.0.1", True), ((3, 11), "1.0.1", False), ((3, 9), "3.1.4", False)]
)
def test_runtime_qualification_is_explicit(monkeypatch, python, werkzeug, expected):
    monkeypatch.setattr(module, "sys", SimpleNamespace(version_info=python))
    monkeypatch.setattr(module.metadata, "version", lambda _: werkzeug)
    assert module.qualified_runtime() is expected


def test_missing_distribution_is_not_qualified(monkeypatch):
    monkeypatch.setattr(module, "sys", SimpleNamespace(version_info=(3, 9)))

    def absent(_):
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(module.metadata, "version", absent)
    assert module.qualified_runtime() is False


@pytest.fixture
def wire():
    records = {"parsed": [], "requests": [], "dropped": []}
    media = b'--fixture\r\nContent-Type: image/jpeg\r\nContent-Length: 11\r\nX-Rider-Source: {"frame_id":"one"}\r\n\r\n\xff\xd8fixture\xff\xd9\r\n--fixture--\r\n'

    class Handler(module.PassiveReadRequestHandler):
        timeout = 0.2  # Only this isolated fixture uses a short idle wait.

        def parse_request(self):
            parsed = super().parse_request()
            if parsed:
                records["parsed"].append((self.command, self._rider_force_close, self.close_connection))
            return parsed

        def connection_dropped(self, error, environ=None):
            records["dropped"].append(type(error).__name__)
            return super().connection_dropped(error, environ)

        def log(self, *_args, **_kwargs):
            pass

    def application(environ, start_response):
        path, method = environ["PATH_INFO"], environ["REQUEST_METHOD"]
        records["requests"].append((environ["REMOTE_PORT"], path, method))
        if path == "/stream":
            start_response("200 OK", [("Content-Type", "multipart/x-mixed-replace; boundary=fixture")])
            return iter((media[:15], media[15:]))
        if path == "/expect":
            assert environ["wsgi.input"].read(int(environ["CONTENT_LENGTH"])) == b"abc"
        if path in {"/204", "/304"}:
            start_response(path[1:] + " fixture", [])
            return []
        code = "415 Unsupported Media Type" if path == "/reject" else "200 OK"
        body = b'{"ok":true}'
        headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
        if path == "/writer-close":
            headers.append(("Connection", "close"))
        start_response(code, headers)
        return [b"" if method == "HEAD" else body]

    server = make_server("127.0.0.1", 0, application, threaded=True, request_handler=Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_port, records, media
    finally:
        server.shutdown()
        server.server_close()
        worker.join(1)


def test_finite_gets_preserve_json_and_honor_writer_close_decisions(wire):
    port, records, _ = wire
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        closed = []
        for _ in range(3):
            connection.request("GET", "/json")
            response = connection.getresponse()
            closed.append(response.will_close)
            assert response.status == 200
            assert json.loads(response.read()) == {"ok": True}
        assert records["parsed"] == [("GET", False, False)] * 3
        peers = {row[0] for row in records["requests"]}
        if metadata.version("werkzeug") == "1.0.1":
            assert closed == [False] * 3
            assert len(peers) == 1
        else:
            # Modern Werkzeug's unconditional close must never be undone.
            assert closed == [True] * 3
            assert len(peers) == 3
    finally:
        connection.close()


@pytest.mark.parametrize(
    "method,extra",
    [
        ("POST", []),
        ("PUT", []),
        ("PATCH", []),
        ("DELETE", []),
        ("OPTIONS", []),
        ("GET", []),
        ("HEAD", []),
        ("GET", ["Content-Length: 0"]),
        ("GET", ["Transfer-Encoding: chunked"]),
    ],
)
def test_unread_body_rejection_closes_before_any_pipelined_request(wire, method, extra):
    port, records, _ = wire
    hidden_request = b"GET /json HTTP/1.1\r\nHost: localhost\r\n\r\n"
    lines = [
        method + " /reject HTTP/1.1",
        "Host: localhost",
        "Content-Type: application/json",
        "Content-Length: " + str(len(hidden_request)),
    ] + extra
    request = ("\r\n".join(lines) + "\r\n\r\n").encode() + hidden_request + hidden_request
    with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
        connection.sendall(request)
        connection.shutdown(socket.SHUT_WR)
        received = b""
        while True:
            data = connection.recv(4096)
            if not data:
                break
            received += data
    assert received.startswith(b"HTTP/1.1 415")
    assert received.count(b"HTTP/1.1 ") == 1
    assert b"Connection: close" in received
    assert len(records["requests"]) == 1
    assert records["parsed"] == [(method, True, True)]


@pytest.mark.parametrize(
    "version,headers",
    [
        ("HTTP/1.0", []),
        ("HTTP/1.1", ["Connection: close"]),
        ("HTTP/1.1", ["Connection: keep-alive, CLOSE"]),
        ("HTTP/1.1", ["Content-Length: 0", "Content-Length: 0"]),
        ("HTTP/1.1", ["Content-Length: invalid"]),
        ("HTTP/1.1", ["Expect: other"]),
    ],
)
def test_legacy_or_ambiguous_reads_are_explicitly_closed(wire, version, headers):
    port, records, _ = wire
    request = ("\r\n".join(["GET /json " + version, "Host: localhost"] + headers) + "\r\n\r\n").encode()
    with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
        connection.sendall(request)
        response = http.client.HTTPResponse(connection)
        response.begin()
        assert response.will_close
        assert json.loads(response.read()) == {"ok": True}
    assert records["parsed"][0] == ("GET", True, True)


def test_expect_100_has_one_interim_response_and_final_close(wire):
    port, records, _ = wire
    with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
        connection.sendall(
            b"POST /expect HTTP/1.1\r\nHost: localhost\r\nContent-Length: 3\r\nExpect: 100-continue\r\n\r\n"
        )
        with connection.makefile("rb") as stream:
            assert stream.readline() == b"HTTP/1.1 100 Continue\r\n"
            assert stream.readline() == b"\r\n"
            connection.sendall(b"abc")
            connection.shutdown(socket.SHUT_WR)
            assert stream.readline().startswith(b"HTTP/1.1 200")
            headers = {}
            while True:
                line = stream.readline()
                if line == b"\r\n":
                    break
                key, value = line.decode().split(":", 1)
                headers[key.lower()] = value.strip()
            assert headers["connection"].lower() == "close"
            assert json.loads(stream.read(int(headers["content-length"]))) == {"ok": True}
    assert records["parsed"] == [("POST", True, True)]


@pytest.mark.parametrize("method,path", [("HEAD", "/json"), ("GET", "/204"), ("GET", "/304")])
def test_bodyless_responses_keep_their_framing(wire, method, path):
    port, records, _ = wire
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        assert response.status == (200 if path == "/json" else int(path[1:]))
        assert response.read() == b""
        assert records["parsed"][0] == (method, False, False)
    finally:
        connection.close()


def test_unknown_length_multipart_stays_close_delimited_and_byte_exact(wire):
    port, _, media = wire
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", "/stream")
        response = connection.getresponse()
        assert response.status == 200
        assert response.will_close
        assert response.headers["Content-Type"].startswith("multipart/x-mixed-replace")
        assert response.read() == media
    finally:
        connection.close()


def test_idle_connection_is_released_without_starting_a_request(wire):
    port, records, _ = wire
    assert module.PassiveReadRequestHandler.timeout == 10.0
    with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
        assert connection.recv(1) == b""
    assert records["requests"] == []


def test_application_close_header_is_honored(wire):
    port, _, _ = wire
    with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
        connection.sendall(b"GET /writer-close HTTP/1.1\r\nHost: localhost\r\n\r\n")
        response = http.client.HTTPResponse(connection)
        response.begin()
        assert response.will_close
        assert json.loads(response.read()) == {"ok": True}
        assert connection.recv(1) == b""
