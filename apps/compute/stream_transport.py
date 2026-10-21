"""Passive stream readiness reads over the same identity-pinned LAN transport."""

from __future__ import annotations

import io
import urllib.error
from urllib.parse import urlsplit

from common.compute_url import transport_options

from .errors import ComputeError
from .lan_transport import PeerHTTPTransport


class StreamStatusTransport:
    def __init__(self, selection, *, clock):
        self.peer = PeerHTTPTransport(selection["url"], clock=clock, **transport_options(selection))

    def open(self, request, *, timeout):
        parsed = urlsplit(request.full_url)
        if (
            (parsed.scheme, parsed.hostname, parsed.port) != self.peer.origin
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.path != "/api/v1/rider/compute/vision/status"
            or parsed.query not in {"", "stream=true"}
            or request.get_method() != "GET"
        ):
            raise ComputeError("navigation_transport_target_invalid")
        status, headers, body = self.peer.request(
            "GET",
            parsed.path + ("?" + parsed.query if parsed.query else ""),
            dict(request.header_items()),
            b"",
            timeout,
            max_bytes=16384,
        )
        if not 200 <= status < 300:
            raise urllib.error.HTTPError(request.full_url, status, "navigation_http_error", headers, io.BytesIO(body))
        return io.BytesIO(body)

    def close(self):
        self.peer.close()
