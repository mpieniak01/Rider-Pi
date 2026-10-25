"""Bounded on-demand proxy to the selected Venom; no local model registry."""

from __future__ import annotations

import json

from apps.compute.client import ComputeError
from apps.compute.lan_transport import PeerHTTPTransport
from common.compute_url import transport_options
from services import compute_config
from services.perception_selection import MODEL_ENGINES

PREFIX = "/api/v1/rider/compute/vision/"
MAX_BYTES = 128 * 1024
JSON_MIME = "application/json"


def _selected():
    selected = compute_config.selected_executor()
    if selected is None:
        raise ComputeError("compute_executor_not_selected", 503)
    return selected


def _host_error_code(raw):
    try:
        error = json.loads(raw)
        candidate = error.get("detail", error.get("error"))
        if isinstance(candidate, dict):
            candidate = candidate.get("code")
        if isinstance(candidate, str) and candidate.replace("_", "").isalnum() and len(candidate) <= 128:
            return candidate
    except (ValueError, TypeError, AttributeError):
        pass
    return "navigation_model_host_unavailable"


def _response_data(response_headers, raw):
    mime = next((value for key, value in response_headers.items() if key.lower() == "content-type"), "")
    if mime.split(";", 1)[0].strip().lower() != JSON_MIME:
        raise ComputeError("navigation_model_host_response_invalid", 502)
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ComputeError("navigation_model_host_response_invalid", 502) from exc
    if not isinstance(data, dict) or len(raw) > MAX_BYTES:
        raise ComputeError("navigation_model_host_response_invalid", 502)
    return data


def _request(suffix, body=None, *, transport_factory=PeerHTTPTransport):
    selected = _selected()
    transport = transport_factory(selected["url"], **transport_options(selected))
    try:
        headers = {
            "Authorization": "Bearer " + selected["token"],
            "X-Rider-Device": selected["device_id"],
            "Accept": JSON_MIME,
        }
        payload = None
        if body is not None:
            headers["Content-Type"] = JSON_MIME
            payload = json.dumps(body, allow_nan=False).encode()
        status, response_headers, raw = transport.request(
            "POST" if body is not None else "GET",
            PREFIX + suffix,
            headers,
            payload,
            10.0 if body is not None else 3.0,
            max_bytes=MAX_BYTES,
        )
        if compute_config.snapshot()["revision"] != selected["revision"]:
            raise ComputeError("compute_selection_changed", 409)
        if not 200 <= status < 300:
            raise ComputeError(_host_error_code(raw), status if 400 <= status <= 599 else 503)
        return _response_data(response_headers, raw)
    finally:
        transport.close()


def catalog():
    """Fresh host observation; intentionally never cache or persist this data."""
    return _request("models")


def choose(body):
    if (
        not isinstance(body, dict)
        or set(body) != {"revision", "model_id"}
        or type(body["revision"]) is not int
        or body["revision"] < 0
        or not isinstance(body["model_id"], str)
        or body["model_id"] not in MODEL_ENGINES
    ):
        raise ValueError("navigation_model_selection_invalid")
    # Host rechecks readiness and resolves the exact artifact; Pi never accepts
    # a user-supplied URL or filename and never guesses installation status.
    return _request("model", body)
