#!/usr/bin/env python3
"""Helpers for forwarding control commands to the motion bridge.

Zasady:
- Router ma być cienki: walidacja → delegacja.
- Sprzęt za mostkiem (8081); tutaj tylko HTTP forward.
- Błędy walidacji zwracają 400 lokalnie (bez forwardu).
- Kody z mostka propagujemy (nie zamieniamy 400→502).
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Dict, Tuple, Literal

from flask import Response, jsonify, make_response, request

MOTION_BRIDGE_URL = (
    os.getenv("MOTION_BRIDGE_URL")
    or os.getenv("WEB_BRIDGE_URL")
    or "http://127.0.0.1:8081"
)
HTTP_TIMEOUT_S = float(os.getenv("WEB_BRIDGE_TIMEOUT", "0.8"))
SAFE_MAX_T = float(os.getenv("SAFE_MAX_DURATION", "0.5"))  # s, miękki limit pojedynczego ruchu

AllowedDir = Literal["forward", "backward", "left", "right"]


# ───────────────────────────── helpers ───────────────────────────── #

def _corsify(resp: Response) -> Response:
    """Attach permissive CORS headers."""
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp


def _decode_json(raw: bytes) -> Dict[str, Any]:
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {"ok": False, "error": "bad json from web bridge", "text": raw[:300].decode("utf-8", "ignore")}


def _proxy_get(path: str, qs_dict: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    """Forward a GET request to the motion bridge."""
    url = f"{MOTION_BRIDGE_URL}{path}"
    if qs_dict:
        url += "?" + urllib.parse.urlencode(qs_dict, doseq=True)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
        raw = resp.read()
        code = resp.status
        ctype = resp.headers.get("Content-Type", "application/json") or "application/json"
    body = _decode_json(raw) if ctype.startswith("application/json") else {
        "ok": False,
        "error": "bad content-type from web bridge",
        "text": raw[:300].decode("utf-8", "ignore"),
    }
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
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            raw = resp.read()
            code = resp.status
            ctype = resp.headers.get("Content-Type", "application/json") or "application/json"
    except Exception as e:  # network errors / bridge down
        return {"ok": False, "error": f"bridge unavailable: {e}"}, 502

    body = _decode_json(raw) if ctype.startswith("application/json") else {
        "ok": False,
        "error": "bad content-type from web bridge",
        "text": raw[:300].decode("utf-8", "ignore"),
    }
    return body, code


# ───────────────────────────── validation ───────────────────────────── #

class BadRequest(ValueError):
    """400 – invalid client payload."""


def _as_float(x: Any, key: str) -> float:
    try:
        return float(x)
    except Exception as e:
        raise BadRequest(f"{key} must be a number") from e


def _validate_dir(d: Any) -> AllowedDir:
    if d not in ("forward", "backward", "left", "right"):
        raise BadRequest("dir must be one of: forward, backward, left, right")
    return d  # type: ignore[return-value]


def _validate_control_payload(p: Dict[str, Any]) -> Tuple[str, float, float]:
    """
    Minimalna walidacja:
      - cmd ∈ {"move","stop"}
      - gdy move: dir w dozwolonym zbiorze
      - v ∈ [0,1]
      - t ∈ (0, SAFE_MAX_T]
    Zwraca (dir, v, t); dla 'stop' wartości nie mają znaczenia.
    """
    if not isinstance(p, dict):
        raise BadRequest("payload must be a JSON object")

    cmd = (str(p.get("cmd") or p.get("action") or "")).lower().strip()
    # aliasy zgodności
    if "direction" in p and "dir" not in p:
        p["dir"] = p["direction"]
    if not cmd and "dir" in p:
        cmd = "move"

    if cmd not in ("move", "stop"):
        raise BadRequest("cmd must be 'move' or 'stop'")

    if cmd == "stop":
        return ("forward", 0.0, 0.0)

    # move:
    if "dir" not in p:
        raise BadRequest("missing 'dir' for move")

    dir_ = _validate_dir(p.get("dir"))
    v = _as_float(p.get("v", 0.0), "v")
    t = _as_float(p.get("t", 0.0), "t")

    if not (0.0 <= v <= 1.0):
        raise BadRequest("v must be in range [0.0, 1.0]")
    if not (0.0 < t <= SAFE_MAX_T):
        raise BadRequest(f"t must be in range (0.0, {SAFE_MAX_T}]")

    return dir_, v, t


# ───────────────────────────── public handlers ───────────────────────────── #

def control_proxy_core() -> tuple[dict[str, Any], int]:
    """Interpret control command and forward to the motion bridge."""
    data = request.get_json(force=False, silent=True) or {}

    # 1) Lokalna walidacja – BEFORE any forward
    try:
        dir_, v, t = _validate_control_payload(dict(data))  # kopia, bo modyfikujemy aliasy
    except BadRequest as e:
        return {"ok": False, "error": str(e)}, 400

    # 2) Delegacja po walidacji:
    #    - 'stop' → GET /api/stop
    #    - 'move' → GET /api/move?dir=&v=&t=[&w=]
    cmd = (str(data.get("cmd") or data.get("action") or "")).lower().strip()
    if not cmd and "dir" in data:
        cmd = "move"

    if cmd == "stop" or data.get("stop") is True:
        try:
            return _proxy_get("/api/stop", None)
        except Exception as e:  # network errors
            return {"ok": False, "error": f"proxy_stop_failed: {e}"}, 502

    # move:
    qs = {"dir": dir_, "v": v, "t": t}
    if "w" in data:
        qs["w"] = data["w"]  # w nie walidujemy, zgodnie z kontraktem (backward-compat)

    try:
        return _proxy_get("/api/move", qs)
    except Exception as e:  # network errors
        return {"ok": False, "error": f"proxy_move_failed: {e}"}, 502


def control_proxy_handler():
    """Handle /api/control and /api/cmd with CORS preflight."""
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    try:
        body, code = control_proxy_core()
        return _corsify(jsonify(body)), code
    except Exception as e:  # runtime errors (nie spodziewane)
        # ważne: NIE maskujemy 4xx z core; tu łapiemy tylko nieprzewidziane wyjątki
        return _corsify(jsonify({"ok": False, "error": f"proxy_control_failed: {e}"})), 502


def proxy_move_get():
    """GET compatibility wrapper for /api/move."""
    try:
        body, code = _proxy_get("/api/move", request.args.to_dict(flat=False))
    except Exception as e:  # network errors
        body, code = {"ok": False, "err": f"proxy_move_failed: {e}"}, 502
    return jsonify(body), code


def proxy_stop_get():
    """GET compatibility wrapper for /api/stop."""
    try:
        body, code = _proxy_get("/api/stop", None)
    except Exception as e:  # network errors
        body, code = {"ok": False, "err": f"proxy_stop_failed: {e}"}, 502
    return jsonify(body), code