"""Bounded persistent vision HTTP; no retries, redirects or actuator requests."""

from __future__ import annotations

import http.client
import io
import socket
import time
import urllib.error
from urllib.parse import urlsplit

from apps.compute.client import ComputeError
from common.compute_url import validate_compute_url

from .http_budget import CaptureBudgetExpired, apply_http_budget
from .lan_transport import PeerHTTPTransport

MAX_RESPONSE = 16384
PREFIX = "/api/v1/rider/compute/vision/"


class NavigationHTTPTransport:
    def __init__(self, base_url, *, clock=time.monotonic, transport_profile="secure", expected_peer_id=None):
        try:
            parsed = validate_compute_url(
                base_url,
                allow_api_path=True,
                transport_profile=transport_profile,
                expected_peer_id=expected_peer_id,
            )
        except ValueError as exc:
            raise ComputeError(str(exc), 400) from None
        self.origin = (parsed.scheme, parsed.hostname, parsed.port)
        self.clock = clock
        self.connection = None
        self.last_response = None
        self.closed = False
        self.connections = 0
        self.requests = 0
        self.peer = (
            PeerHTTPTransport(
                base_url,
                transport_profile=transport_profile,
                expected_peer_id=expected_peer_id,
                clock=clock,
            )
            if expected_peer_id
            else None
        )
        self.generation = None

    def _discard(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def close(self):
        self.closed = True
        if self.peer is not None:
            self.peer.close()
        self._discard()

    def status(self):
        if self.peer is not None:
            return {"connections": self.peer.connections, "requests": self.peer.requests, **self.peer.status()}
        return {"connections": self.connections, "requests": self.requests}

    def _validated_target(self, request):
        parsed = urlsplit(request.full_url)
        if (
            (parsed.scheme, parsed.hostname, parsed.port) != self.origin
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {PREFIX + "decision", PREFIX + "decision-reference"}
            or request.get_method() != "POST"
        ):
            raise ComputeError("navigation_transport_target_invalid")
        return parsed

    def _prepare_connection(self, parsed, timeout):
        if self.last_response is not None and self.clock() - self.last_response >= 2.0:
            self._discard()
        if self.connection is None:
            cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
            self.connection = cls(parsed.hostname, parsed.port, timeout=timeout)
            self.connections += 1
        connection = self.connection
        connection.timeout = timeout
        if connection.sock is not None:
            connection.sock.settimeout(timeout)
        return connection

    def open(self, request, *, timeout):
        if self.closed:
            raise ComputeError("navigation_transport_closed")
        parsed = self._validated_target(request)
        if self.peer is not None:
            return self._open_peer(request, parsed, timeout)
        deadline = self.clock() + timeout
        connection = self._prepare_connection(parsed, timeout)
        try:
            # Connect, request, headers and body share one original budget.
            if connection.sock is None and callable(getattr(connection, "connect", None)):
                connection.connect()
            apply_http_budget(connection, deadline, self.clock)
            self.requests += 1
            connection.request("POST", parsed.path, body=request.data, headers=dict(request.header_items()))
            response = connection.getresponse()
            body = response.read(MAX_RESPONSE + 1)
            if len(body) > MAX_RESPONSE:
                raise ComputeError("navigation_response_bounds")
            self.last_response = self.clock()
            if 300 <= response.status < 400:
                raise ComputeError("navigation_redirect_denied")
            if not 200 <= response.status < 300:
                raise urllib.error.HTTPError(
                    request.full_url, response.status, "navigation_http_error", response.headers, io.BytesIO(body)
                )
            return io.BytesIO(body)
        except urllib.error.HTTPError:
            # The bounded body was consumed. Observation may try a NEW capture;
            # this POST is never replayed and its original deadline is unchanged.
            raise
        except (OSError, http.client.HTTPException) as exc:
            self._discard()
            if isinstance(exc, CaptureBudgetExpired):
                raise
            if isinstance(exc, (TimeoutError, socket.timeout)) and self.clock() >= deadline:
                raise CaptureBudgetExpired("navigation_capture_deadline") from None
            if isinstance(exc, (TimeoutError, socket.timeout)):
                raise TimeoutError("navigation_transport_timeout") from None
            raise urllib.error.URLError("navigation_transport_unavailable") from None
        except Exception:
            self._discard()
            raise

    def _open_peer(self, request, parsed, timeout):
        deadline = self.clock() + timeout
        try:
            status, headers, body = self.peer.request(
                "POST",
                parsed.path,
                dict(request.header_items()),
                request.data,
                timeout,
                max_bytes=MAX_RESPONSE,
                generation=self.generation,
            )
            self.generation = self.peer.generation
        except ComputeError as exc:
            if exc.code == "transport_timeout" and self.clock() >= deadline:
                raise CaptureBudgetExpired("navigation_capture_deadline") from None
            if exc.code == "transport_generation_changed":
                # The next explicitly requested capture may use this connection;
                # the current frame/lease is rejected, never replayed.
                self.generation = self.peer.generation
            raise
        if not 200 <= status < 300:
            raise urllib.error.HTTPError(
                request.full_url,
                status,
                "navigation_http_error",
                headers,
                io.BytesIO(body),
            )
        return io.BytesIO(body)
