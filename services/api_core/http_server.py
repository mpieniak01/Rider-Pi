"""Opt-in passive HTTP persistence for the qualified physical Pi runtime."""

from __future__ import annotations

import os
import socket
import sys
from importlib import metadata

from werkzeug.serving import WSGIRequestHandler

FLAG = "RIDER_API_HTTP_KEEPALIVE"
IDLE_READ_TIMEOUT_S = 10.0


class PassiveReadRequestHandler(WSGIRequestHandler):
    """Reuse only bodyless HTTP/1.1 reads; honor every upstream close decision.

    Werkzeug 1.0.1 closes unknown-length streams itself. The socket timeout
    bounds blocked I/O and idle reads, not domain processing or command TTL.
    No Nagle, worker-count, media, request replay or actuator policy changes.
    """

    protocol_version = "HTTP/1.1"
    timeout = IDLE_READ_TIMEOUT_S

    def handle_one_request(self):
        self._rider_force_close = True
        self._rider_close_header_sent = False
        try:
            return super().handle_one_request()
        except (OSError, socket.timeout):
            self.close_connection = True
            raise

    def parse_request(self):
        parsed = super().parse_request()
        if not parsed:
            return False
        lengths = self.headers.get_all("Content-Length", [])
        connections = {
            token.strip().lower() for value in self.headers.get_all("Connection", []) for token in value.split(",")
        }
        eligible = (
            self.request_version == "HTTP/1.1"
            and self.command in {"GET", "HEAD"}
            and (not lengths or len(lengths) == 1 and lengths[0].strip() == "0")
            and not self.headers.get_all("Transfer-Encoding", [])
            and not self.headers.get_all("Expect", [])
            and "close" not in connections
        )
        self._rider_force_close = not eligible
        if self._rider_force_close:
            # An early host/origin/type rejection may leave a request body unread.
            # Never interpret that body as the next request; do not drain it.
            self.close_connection = True
        return True

    def send_header(self, keyword, value):
        if keyword.lower() == "connection":
            if getattr(self, "_rider_force_close", True):
                value = "close"
            if "close" in {token.strip().lower() for token in str(value).split(",")}:
                self._rider_close_header_sent = True
        return super().send_header(keyword, value)

    def end_headers(self):
        if getattr(self, "_rider_force_close", True) and not getattr(self, "_rider_close_header_sent", False):
            self.send_header("Connection", "close")
        return super().end_headers()

    def handle_expect_100(self):
        # BaseHTTPRequestHandler would emit 100 after switching to HTTP/1.1,
        # while both qualified Werkzeug and modern versions emit it in run_wsgi.
        return True

    def connection_dropped(self, error, environ=None):
        self.close_connection = True
        return super().connection_dropped(error, environ)


def qualified_runtime():
    try:
        return sys.version_info[:2] == (3, 9) and metadata.version("werkzeug") == "1.0.1"
    except metadata.PackageNotFoundError:
        return False


def server_options():
    """No flag preserves old server behavior; explicit unsupported opt-in fails."""
    flag = os.getenv(FLAG, "").strip().lower()
    if flag in {"", "0", "false", "off"}:
        return {}
    if flag not in {"1", "true", "on"}:
        raise RuntimeError("http_keepalive_flag_invalid")
    if not qualified_runtime():
        raise RuntimeError("http_keepalive_runtime_unsupported")
    return {"request_handler": PassiveReadRequestHandler}
