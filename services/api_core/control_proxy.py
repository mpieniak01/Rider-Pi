#!/usr/bin/env python3
"""Helpers for forwarding control commands to the motion bridge."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from flask import Response, jsonify, make_response, request

MOTION_BRIDGE_URL = (
    os.getenv("MOTION_BRIDGE_URL")
    or os.getenv("WEB_BRIDGE_URL")
    or "http://127.0.0.1:8081"
)


def _corsify(resp: Response) -> Response:
    """Attach permissive CORS headers."""
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp


def _proxy_get(path: str, qs_dict: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    """Forward a GET request to the motion bridge."""
    url = f"{MOTION_BRIDGE_URL}{path}"
    if qs_dict:
        url += "?" + urllib.parse.urlencode(qs_dict, doseq=True)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        data = resp.read()
        code = resp.status
    body = json.loads(data.decode("utf-8"))
    return body, code


def _proxy_post_json(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Forward a JSON POST request to the motion bridge."""
    url = f"{MOTION_BRIDGE_URL}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            raw = resp.read()
            code = resp.status
            ctype = resp.headers.get("Content-Type", "application/json") or "application/json"
    except Exception as e:  # pragma: no cover - network errors
        return {"ok": False, "error": f"web bridge unreachable: {e}"}, 502

    try:
        if ctype.startswith("application/json"):
            body = json.loads(raw.decode("utf-8"))
        else:
            body = {
                "ok": False,
                "error": "bad content-type from web bridge",
                "text": raw[:300].decode("utf-8", "ignore"),
            }
    except Exception:  # pragma: no cover - decode errors
        body = {
            "ok": False,
            "error": "bad json from web bridge",
            "text": raw[:300].decode("utf-8", "ignore"),
        }
    return body, code


def control_proxy_core() -> tuple[dict[str, Any], int]:
    """Interpret control command and forward to the motion bridge."""
    data = request.get_json(force=False, silent=True) or {}
    cmd = (str(data.get("cmd") or data.get("action") or "")).lower().strip()
    if "direction" in data and "dir" not in data:
        data["dir"] = data["direction"]
    if not cmd and "dir" in data:
        cmd = "move"

    if cmd == "move":
        qs = {k: data[k] for k in ("dir", "v", "t", "w") if k in data}
        if "dir" not in qs:
            return {"ok": False, "error": "missing 'dir' for move"}, 400
        return _proxy_get("/api/move", qs)

    if cmd == "stop" or data.get("stop") is True:
        return _proxy_get("/api/stop", None)

    body, code = _proxy_post_json("/api/control", data)
    if code == 404:
        body, code = _proxy_post_json("/control", data)
    return body, code


def control_proxy_handler():
    """Handle /api/control and /api/cmd with CORS preflight."""
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    try:
        body, code = control_proxy_core()
        return _corsify(jsonify(body)), code
    except Exception as e:  # pragma: no cover - runtime errors
        return _corsify(jsonify({"ok": False, "error": f"proxy_control_failed: {e}"})), 502


def proxy_move_get():
    """GET compatibility wrapper for /api/move."""
    try:
        body, code = _proxy_get("/api/move", request.args.to_dict(flat=False))
    except Exception as e:  # pragma: no cover - network errors
        body, code = {"ok": False, "err": f"proxy_move_failed: {e}"}, 502
    return jsonify(body), code


def proxy_stop_get():
    """GET compatibility wrapper for /api/stop."""
    try:
        body, code = _proxy_get("/api/stop", None)
    except Exception as e:  # pragma: no cover - network errors
        body, code = {"ok": False, "err": f"proxy_stop_failed: {e}"}, 502
    return jsonify(body), code

