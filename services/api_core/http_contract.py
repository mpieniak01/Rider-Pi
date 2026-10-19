"""One lightweight HTTP envelope; domain protocols and legacy defaults stay intact."""

from __future__ import annotations

import json
import math
import time

from flask import g, jsonify, request
from werkzeug.exceptions import HTTPException

from . import http_security
from .contract_registry import contract_for, projection
from .operation_result import result_for

MEDIA_TYPE = "application/vnd.rider.api+json"
ENVELOPE_VERSION = 1


def negotiated() -> bool:
    return getattr(g, "rider_envelope_version", None) == ENVELOPE_VERSION


def canonical_data(data) -> None:
    """A handler may supply its exact source payload once, without a legacy copy."""
    g.rider_canonical_data = data


def operation(value: dict) -> None:
    """Explicit domain result, containing the actual evidence of the operation."""
    g.rider_operation = value


def _accept_version(header: str):
    offered = []
    for item in header.split(","):
        parts = [part.strip() for part in item.split(";")]
        if parts[0].lower() != MEDIA_TYPE:
            continue
        parameters = {
            key.strip().lower(): value.strip().strip('"')
            for key, value in (part.split("=", 1) for part in parts[1:] if "=" in part)
        }
        try:
            quality = float(parameters.get("q", "1"))
        except ValueError:
            quality = 0
        if 0 < quality <= 1:
            offered.append((quality, parameters.get("version", "missing")))
    if not offered:
        return None
    supported = [quality for quality, version in offered if version == "1"]
    return "1" if supported else max(offered, key=lambda row: row[0])[1]


def _finite_time(value):
    try:
        return value if type(value) in (int, float) and math.isfinite(value) and value > 0 else None
    except OverflowError:
        return None


def _observed(payload, rule):
    if not isinstance(payload, dict):
        return None
    if rule in {"/state", "/healthz", "/api/devices", "/api/providers/state", "/api/services/graph"}:
        return None
    if "observed_at" in payload:
        return _finite_time(payload["observed_at"])
    if "ts" in payload:
        return _finite_time(payload["ts"])
    safety = payload.get("safety")
    return _observed(safety, None) if isinstance(safety, dict) else None


def _error(payload, code):
    value = payload.get("error") if isinstance(payload, dict) else None
    if not value and isinstance(payload, dict) and isinstance(payload.get("result"), dict):
        value = payload["result"].get("error")
    if code < 400 and isinstance(value, str) and value.startswith("sensor_quality:"):
        return None
    if isinstance(value, dict) and value:
        return {
            "code": str(value.get("code", "domain_error"))[:128],
            "message": str(value.get("message", value.get("code", "")))[:512],
            "retryable": value.get("retryable") is True,
            **({"details": value["details"]} if "details" in value else {}),
        }
    if value:
        return {"code": str(value)[:128], "message": str(value)[:512], "retryable": False}
    if code >= 400:
        return {"code": f"http_{code}", "message": "Request failed", "retryable": False}
    return None


def _apply_operation_status(response, result) -> None:
    """Map unconfirmed success to its HTTP state without replacing domain errors."""
    if result is None or response.status_code >= 400:
        return
    if result["status"] == "pending":
        response.status_code = 202
    elif result["status"] == "unknown":
        response.status_code = 502
    elif result["status"] == "partial":
        response.status_code = 409


def _build_envelope(response, payload, rule):
    """Combine domain data and operation evidence after resolving the HTTP status."""
    contract = contract_for(rule)
    body = payload if isinstance(payload, dict) else {}
    submitted = request.get_json(silent=True) if request.is_json else None
    result = getattr(g, "rider_operation", None)
    if result is None:
        result = result_for(rule, body, response.status_code, submitted)
    _apply_operation_status(response, result)
    error = _error(payload, response.status_code)
    now = time.time()
    data = g.rider_canonical_data if hasattr(g, "rider_canonical_data") else projection(rule, payload)
    return {
        "meta": {
            "envelope_version": ENVELOPE_VERSION,
            "contract_id": contract.name,
            "contract_version": contract.version,
            "host": "pi",
            "source": body.get("source", "pi"),
            "observed_at": _observed(payload, rule),
            "generated_at": now,
            "server_time": now,
            "stale": body.get("stale") is True,
            "offline": body.get("offline") is True,
            "partial": body.get("partial") is True
            or bool(body.get("error"))
            and error is None
            or result is not None
            and result["status"] == "partial",
        },
        "ok": bool(
            response.status_code < 400
            and error is None
            and (result is None or result["status"] == "executed" and result["confirmed"])
        ),
        "data": data,
        "error": error,
        "operation": result,
    }


def _encode_envelope(response, wrapped):
    """Keep invalid source values out of JSON and expose a protocol failure."""
    try:
        return json.dumps(wrapped, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, OverflowError):
        response.status_code = 502
        wrapped.update(
            ok=False,
            data=None,
            operation=None,
            error={
                "code": "invalid_domain_payload",
                "message": "Source payload is not finite JSON",
                "retryable": False,
            },
        )
        wrapped["meta"]["partial"] = True
        return json.dumps(wrapped, ensure_ascii=False, allow_nan=False)


def enhance(response):
    """Binary/SSE MIME and payload are preserved; JSON is negotiated on the same URL."""
    response.vary.add("Accept")
    http_security.apply_cors(response)
    response.headers["Access-Control-Expose-Headers"] = (
        "X-Rider-Contract,X-Rider-Observed-At,X-Rider-File-Observed-At,X-Rider-Source,"
        "X-Rider-Frame-Id,X-Rider-Stream,X-Rider-Stale,X-Rider-Placeholder,Last-Modified,"
        "X-Rider-Source-Json,X-Rider-Frame-Age-Ms,X-Rider-Frame-Age-Source,X-Rider-Sequence,"
        "X-Rider-Camera-Session,X-Rider-Transport-Epoch,X-Rider-Pipeline-Revision,X-Rider-Captured-Monotonic-Ns"
    )
    if request.path.startswith("/web/assets/operator/") and request.path.endswith(".js"):
        response.headers["Cache-Control"] = "no-cache"
    if not negotiated() or response.status_code in {204, 304} or not response.is_json:
        return response
    payload = response.get_json(silent=True)
    previous_meta = payload.get("meta") if isinstance(payload, dict) else None
    if isinstance(previous_meta, dict) and previous_meta.get("envelope_version") == ENVELOPE_VERSION:
        return response
    rule = request.url_rule.rule if request.url_rule else None
    wrapped = _build_envelope(response, payload, rule)
    response.set_data(_encode_envelope(response, wrapped))
    response.headers["Content-Type"] = MEDIA_TYPE + ";version=1"
    response.headers["Cache-Control"] = "no-store"
    return response


def install(app, *, after_request: bool = False) -> None:
    http_security.install(app)
    if app.extensions.get("rider_http_contract"):
        return
    app.extensions["rider_http_contract"] = True
    if after_request:
        app.after_request(enhance)

    @app.before_request
    def accept_contract():
        version = _accept_version(request.headers.get("Accept", ""))
        g.rider_envelope_version = 1 if version is not None else None
        if version not in {None, "1"}:
            return jsonify({"ok": False, "error": "unsupported_envelope_version", "supported": [1]}), 406
        if negotiated() and request.method == "OPTIONS" and request.url_rule is not None:
            return "", 204

    @app.errorhandler(HTTPException)
    def http_error(exc):
        if not negotiated():
            return exc.get_response()
        response = exc.get_response()
        response.set_data(json.dumps({"ok": False, "error": exc.name.lower().replace(" ", "_")}))
        response.content_type = "application/json"
        return response
