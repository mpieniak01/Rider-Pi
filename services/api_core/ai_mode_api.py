#!/usr/bin/env python3
"""
AI Mode API - Control endpoints for AI processing mode management

Provides REST API endpoints to query and change the AI processing mode
between "local" (all processing on Pi) and "pc_offload" (heavy processing on PC).
"""

from __future__ import annotations

import json
import time

from flask import Response, request

from common import ai_mode
from common.bus import TOPIC_SYSTEM_AI_MODE_CHANGED

from . import compat as C


def api_ai_mode_get():
    """
    GET /api/system/ai-mode

    Returns current AI mode and timestamp of last change.

    Response: {"ok": true, "mode": "local"|"pc_offload", "changed_ts": float}
    """
    if request.method == "OPTIONS":
        resp = Response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET,OPTIONS"
        return resp

    try:
        mode_info = ai_mode.get_mode_info()
        result = {
            "ok": True,
            "mode": mode_info["mode"],
            "changed_ts": mode_info["changed_ts"],
        }
        resp = Response(json.dumps(result), mimetype="application/json")
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
    except Exception as e:
        resp = Response(
            json.dumps({"ok": False, "error": str(e)}),
            mimetype="application/json",
            status=500,
        )
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp


def api_ai_mode_set():
    """
    PUT /api/system/ai-mode
    POST /api/system/ai-mode

    Changes the AI processing mode.

    Request body: {"mode": "local"|"pc_offload"}
    Response: {"ok": true, "mode": str, "changed_ts": float}
    """
    if request.method == "OPTIONS":
        resp = Response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "PUT,POST,OPTIONS"
        return resp

    data = request.get_json(silent=True) or {}
    new_mode = data.get("mode")

    if not new_mode:
        resp = Response(
            json.dumps({"ok": False, "error": "Missing 'mode' field in request body"}),
            mimetype="application/json",
            status=400,
        )
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    if new_mode not in ("local", "pc_offload"):
        resp = Response(
            json.dumps(
                {
                    "ok": False,
                    "error": f"Invalid mode '{new_mode}'. Must be 'local' or 'pc_offload'",
                }
            ),
            mimetype="application/json",
            status=400,
        )
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    try:
        # Update the mode
        result = ai_mode.set_mode(new_mode)  # type: ignore

        # Publish ZMQ event to notify all subscribers
        event_payload = {
            "mode": result["mode"],
            "changed_ts": result["changed_ts"],
            "ts": time.time(),
        }
        C.bus_pub(TOPIC_SYSTEM_AI_MODE_CHANGED, event_payload)

        # Return success response
        resp = Response(json.dumps(result), mimetype="application/json")
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
    except ValueError as e:
        resp = Response(
            json.dumps({"ok": False, "error": str(e)}),
            mimetype="application/json",
            status=400,
        )
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
    except Exception as e:
        resp = Response(
            json.dumps({"ok": False, "error": str(e)}),
            mimetype="application/json",
            status=500,
        )
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
