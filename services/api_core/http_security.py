"""One browser boundary for JSON APIs and explicitly supported binary uploads."""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit

from flask import jsonify, request

_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
_UPLOADS = {"/api/asr", "/api/voice/asr", "/api/voice/playback", "/api/compute/tasks/<task>"}
_METHODS = "GET,POST,PUT,PATCH,DELETE,OPTIONS,HEAD"
_HEADERS = "Content-Type,Accept,Authorization,X-Rider-Params,X-Rider-Playback-Id,X-Rider-Playback-TTL-Ms"


def _origin(value):
    if (
        not value
        or any(char in value for char in "?#\\")
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or "*" in parsed.netloc
        ):
            return None
        port = parsed.port
        if parsed.netloc.endswith(":"):
            return None
        return (
            parsed.scheme,
            parsed.hostname.lower(),
            port if port is not None else (443 if parsed.scheme == "https" else 80),
        )
    except ValueError:
        return None


def trusted_host():
    """Host is request input; never use an arbitrary DNS name as CSRF authority."""
    # Parse raw authority before Werkzeug normalizes it (invalid ports/brackets may raise).
    authority = request.headers.get("Host")
    target = (
        _origin(f"{request.scheme}://{authority}") if authority is not None else _origin(request.host_url.rstrip("/"))
    )
    if target is None:
        return False
    host = target[1]
    try:
        address = ipaddress.ip_address(host)
        if address.is_private or address.is_loopback or address.is_link_local:
            return True
    except ValueError:
        # A name is trusted only from local/operator configuration, never DNS lookup of Host.
        pass
    hostname = socket.gethostname().lower()
    names = {"localhost", hostname, hostname + ".local"}
    names.update(value.strip().lower() for value in os.getenv("RIDER_TRUSTED_HOSTS", "").split(",") if value.strip())
    origins = (_origin(value.strip()) for value in os.getenv("RIDER_ALLOWED_ORIGINS", "").split(","))
    names.update(origin[1] for origin in origins if origin is not None)
    return host in names


def allowed_origin():
    origin = _origin(request.headers.get("Origin"))
    if origin is None:
        return False
    allowed = {_origin(request.host_url.rstrip("/"))} if trusted_host() else set()
    allowed.update(_origin(value.strip()) for value in os.getenv("RIDER_ALLOWED_ORIGINS", "").split(","))
    return origin in allowed


def apply_cors(response):
    """Override legacy grants last; unknown origins never inherit a wildcard."""
    response.vary.add("Origin")
    allowed = "Origin" in request.headers and allowed_origin()
    for name in list(response.headers.keys()):
        if name.lower().startswith("access-control-") and (
            not allowed or name.lower().startswith("access-control-allow-")
        ):
            response.headers.remove(name)
    if allowed:
        response.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin")
        response.headers["Access-Control-Allow-Methods"] = _METHODS
        response.headers["Access-Control-Allow-Headers"] = _HEADERS
    return response


def install(app):
    if app.extensions.get("rider_http_security"):
        return
    app.extensions["rider_http_security"] = True
    # Flask runs after_request hooks in reverse order. Install this first so
    # legacy route helpers cannot restore a wildcard after this final filter.
    app.after_request(apply_cors)

    @app.before_request
    def protect_browser_boundary():
        if not trusted_host():
            return jsonify(ok=False, error="host_not_allowed"), 400
        if "Origin" in request.headers and not allowed_origin():
            return jsonify(ok=False, error="origin_not_allowed"), 403
        if request.method not in _UNSAFE:
            return None
        if "Origin" not in request.headers and request.headers.get("Sec-Fetch-Site") in {"cross-site", "same-site"}:
            return jsonify(ok=False, error="origin_required"), 403
        rule = request.url_rule.rule if request.url_rule else None
        has_body = request.content_length not in {None, 0} or request.headers.get("Transfer-Encoding")
        has_body = has_body or request.content_length is None and bool(request.mimetype)
        if (
            rule is not None
            and rule not in _UPLOADS
            and not request.is_json
            and request.content_length in {None, 0}
            and request.environ.get("wsgi.input_terminated")
        ):
            # Read at most one byte only for a request we will reject if nonempty.
            # Never consume a JSON body or an explicitly supported upload stream.
            has_body = bool(request.stream.read(1))

        if rule is not None and has_body and not request.is_json and rule not in _UPLOADS:
            return jsonify(ok=False, error="unsupported_content_type"), 415
        return None
