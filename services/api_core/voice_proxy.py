from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from flask import Response, jsonify, make_response, request

VOICE_URL = os.getenv("VOICE_URL", "http://127.0.0.1:8092")
HTTP_TIMEOUT_S = float(os.getenv("VOICE_TIMEOUT", "0.8"))


def _corsify(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp


def _forward(
    path: str, qs: dict[str, Any] | None, payload: dict[str, Any] | None
) -> tuple[dict[str, Any], int]:
    url = f"{VOICE_URL}{path}"
    if qs:
        url += "?" + urllib.parse.urlencode(qs)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            raw = resp.read()
            code = resp.status
    except TimeoutError:
        return {"ok": False, "error": "voice timeout"}, 504
    except Exception as e:
        return {"ok": False, "error": f"voice unavailable: {e}"}, 502
    try:
        body = json.loads(raw.decode("utf-8"))
    except Exception:
        return {"ok": False, "error": "bad json from voice"}, 502
    return body, code


def capture_handler():
    """Proxy /api/voice/capture."""
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    sec = request.args.get("sec", "")
    try:
        sec_f = float(sec)
    except Exception:
        return _corsify(jsonify({"ok": False, "error": "bad sec"})), 400
    if not (0.5 <= sec_f <= 6.0):
        return _corsify(jsonify({"ok": False, "error": "bad sec"})), 400
    body, code = _forward("/capture", {"sec": sec_f}, None)
    return _corsify(jsonify(body)), code


def say_handler():
    """Proxy /api/voice/say."""
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return _corsify(jsonify({"ok": False, "error": "text required"})), 400
    payload = {"text": text}
    if isinstance(data.get("voice"), str):
        payload["voice"] = data["voice"]
    body, code = _forward("/say", None, payload)
    return _corsify(jsonify(body)), code
