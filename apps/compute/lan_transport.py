"""Demand-driven, identity-pinned connections; requests are never replayed."""

from __future__ import annotations

import http.client
import json
import random
import socket
import threading
import time
from collections import OrderedDict

from common.compute_url import validate_compute_url

from .errors import ComputeError

IDENTITY_PATH = "/api/v1/transport/identity"
_GATES = OrderedDict()
_GATES_LOCK = threading.Lock()


class _Gate:
    def __init__(self):
        self.lock = threading.Lock()
        self.failures = 0
        self.retry_at = 0.0


def _gate(key):
    with _GATES_LOCK:
        if key not in _GATES:
            # Config allows at most eight executors; bound retained failure state.
            if len(_GATES) >= 64:
                _GATES.popitem(last=False)
            _GATES[key] = _Gate()
        _GATES.move_to_end(key)
        return _GATES[key]


class PeerHTTPTransport:
    """Identity and token share a socket, without implicit reconnect or redirects.

    A connection is re-resolved after two idle seconds or at most thirty active
    seconds. The OS resolver owns DNS TTL; no application IP cache is retained.
    The gate coalesces reconnects/backoff for the same configured peer in-process.
    No timer, scan or socket exists until an active caller requests work.
    """

    def __init__(self, base_url, *, transport_profile="secure", expected_peer_id=None, clock=time.monotonic):
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
        self.canonical_url = base_url.rstrip("/")
        self.expected_peer_id = expected_peer_id
        self.clock = clock
        self.connection = None
        self.closed = False
        self.generation = 0
        self.connections = 0
        self.requests = 0
        self.last_response = None
        self.connected_at = None
        self.state = "offline"
        self.error = None
        self._lock = threading.Lock()
        self._gate = _gate((*self.origin, expected_peer_id))

    def status(self):
        return {
            "state": self.state,
            "error": self.error,
            "generation": self.generation,
            "retry_after_s": max(0.0, self._gate.retry_at - self.clock()),
        }

    def _discard(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self.last_response = self.connected_at = None

    def _failed(self, code):
        self._discard()
        gate = self._gate
        gate.failures = min(gate.failures + 1, 6)
        delay = min(30.0, 2.0 ** (gate.failures - 1))
        gate.retry_at = self.clock() + min(30.0, delay * random.uniform(1.0, 1.1))
        self.error = code
        self.state = "identity_mismatch" if code == "transport_identity_mismatch" else "backoff"

    def _remaining(self, deadline):
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise ComputeError("transport_timeout", 504)
        self.connection.timeout = remaining
        if self.connection.sock is not None:
            self.connection.sock.settimeout(remaining)
        return remaining

    def _verify(self, deadline):
        self.state = "verifying_identity"
        self._remaining(deadline)
        # These are the ONLY headers sent before verifying the paired identity.
        self.connection.request("GET", IDENTITY_PATH, headers={"Accept": "application/json"})
        response = self.connection.getresponse()
        data = response.read(4097)
        if 300 <= response.status < 400:
            raise ComputeError("transport_identity_redirect_denied")
        if response.status != 200 or len(data) > 4096:
            raise ComputeError("transport_identity_api_invalid")
        mime = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
        try:
            identity = json.loads(data) if mime == "application/json" else None
        except ValueError:
            identity = None
        if (
            not isinstance(identity, dict)
            or type(identity.get("protocol_version")) is not int
            or identity["protocol_version"] != 1
            or identity.get("service_role") != "venom"
        ):
            raise ComputeError("transport_identity_api_invalid")
        if identity.get("peer_id") != self.expected_peer_id:
            raise ComputeError("transport_identity_mismatch", 409)
        self._remaining(deadline)
        if self.connection.sock is None or response.will_close:
            raise ComputeError("transport_identity_connection_closed")
        # HTTPConnection normally reconnects silently when a socket closes.
        # Prohibit that path: the next TCP socket must pass identity again.
        self.connection.auto_open = 0

    def _prepare(self, deadline):
        if self.closed:
            raise ComputeError("compute_client_closed")
        now = self.clock()
        if self.connection is not None and (
            self.connection.sock is None
            or self.last_response is not None
            and now - self.last_response >= 2.0
            or self.connected_at is not None
            and now - self.connected_at >= 30.0
        ):
            self._discard()
        if self.connection is not None:
            return
        with self._gate.lock:
            if self.clock() < self._gate.retry_at:
                self.state = "backoff"
                raise ComputeError("transport_reconnect_backoff", 503)
            try:
                self.state = "resolving"
                scheme, host, port = self.origin
                cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
                self.connection = cls(host, port, timeout=max(0.01, deadline - self.clock()))
                self.state = "connecting"
                self.connection.connect()
                self.connections += 1
                if self.expected_peer_id:
                    self._verify(deadline)
                self.connected_at = self.clock()
                self.generation += 1
                self.state, self.error = "online", None
                self._gate.failures, self._gate.retry_at = 0, 0.0
            except (OSError, http.client.HTTPException, ComputeError) as exc:
                code = self._failure_code(exc)
                self._failed(code)
                raise ComputeError(code, getattr(exc, "status", 503)) from None

    @staticmethod
    def _failure_code(exc):
        if isinstance(exc, ComputeError):
            return exc.code
        if isinstance(exc, socket.gaierror):
            return "transport_resolve_failed"
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return "transport_timeout"
        return "transport_connect_failed"

    def prepare(self, timeout):
        with self._lock:
            self._prepare(self.clock() + timeout)
            return self.generation

    def request(self, method, path, headers, body, timeout, *, max_bytes, generation=None):
        with self._lock:
            deadline = self.clock() + timeout
            self._prepare(deadline)
            if generation is not None and generation != self.generation:
                raise ComputeError("transport_generation_changed", 409)
            try:
                self._remaining(deadline)
                self.requests += 1
                self.connection.request(method, path, body=body, headers=headers)
                response = self.connection.getresponse()
                data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise ComputeError("transport_response_too_large")
                if 300 <= response.status < 400:
                    raise ComputeError("transport_redirect_denied")
                self._remaining(deadline)
                self.last_response = self.clock()
                return response.status, dict(response.getheaders()), data
            except (OSError, http.client.HTTPException, ComputeError) as exc:
                with self._gate.lock:
                    self._failed(self._failure_code(exc))
                raise ComputeError(self.error, getattr(exc, "status", 503)) from None

    def close(self):
        with self._lock:
            self.closed = True
            self._discard()
            self.state = "offline"
