#!/usr/bin/env python3
"""
Navigator API - Control endpoints for autonomous Rekonesans mode
"""

from __future__ import annotations

import json
import time

from flask import Response, request

from common.bus import TOPIC_NAVIGATOR_RETURN_HOME_START

from . import compat as C

# Navigator topics
TOPIC_NAVIGATOR_CONTROL = "navigator.control"
TOPIC_NAVIGATOR_STATE = "navigator.state"


def api_navigator_start():
    """Start autonomous navigation (Rekonesans mode)"""
    if request.method == "OPTIONS":
        resp = Response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
        return resp

    data = request.get_json(silent=True) or {}
    strategy = data.get("strategy", "STOP")  # STOP or AVOID

    # Validate strategy
    if strategy not in ["STOP", "AVOID"]:
        return Response(
            json.dumps({"ok": False, "error": f"invalid strategy: {strategy}"}),
            mimetype="application/json",
            status=400,
        )

    # Publish start command
    C.bus_pub(
        TOPIC_NAVIGATOR_CONTROL,
        {"action": "start", "strategy": strategy, "ts": time.time()},
    )

    resp = Response(
        json.dumps({"ok": True, "action": "start", "strategy": strategy}),
        mimetype="application/json",
    )
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


def api_navigator_stop():
    """Stop autonomous navigation"""
    if request.method == "OPTIONS":
        resp = Response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
        return resp

    # Publish stop command
    C.bus_pub(TOPIC_NAVIGATOR_CONTROL, {"action": "stop", "ts": time.time()})

    resp = Response(
        json.dumps({"ok": True, "action": "stop"}),
        mimetype="application/json",
    )
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


def api_navigator_config():
    """Configure navigator settings"""
    if request.method == "OPTIONS":
        resp = Response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
        return resp

    data = request.get_json(silent=True) or {}

    # Extract and validate parameters
    config = {}
    if "strategy" in data:
        strategy = data["strategy"]
        if strategy not in ["STOP", "AVOID"]:
            return Response(
                json.dumps({"ok": False, "error": f"invalid strategy: {strategy}"}),
                mimetype="application/json",
                status=400,
            )
        config["strategy"] = strategy

    if "fwd_speed" in data:
        try:
            config["fwd_speed"] = float(data["fwd_speed"])
        except ValueError:
            return Response(
                json.dumps({"ok": False, "error": "invalid fwd_speed value"}),
                mimetype="application/json",
                status=400,
            )

    if "turn_speed" in data:
        try:
            config["turn_speed"] = float(data["turn_speed"])
        except ValueError:
            return Response(
                json.dumps({"ok": False, "error": "invalid turn_speed value"}),
                mimetype="application/json",
                status=400,
            )

    # Publish configuration update
    C.bus_pub(
        TOPIC_NAVIGATOR_CONTROL,
        {"action": "config", "config": config, "ts": time.time()},
    )

    resp = Response(
        json.dumps({"ok": True, "action": "config", "config": config}),
        mimetype="application/json",
    )
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


def api_navigator_status():
    """Get current navigator status (from last published state)"""
    # In a real implementation, this would read from a cache or state store
    # For now, return a placeholder that indicates the endpoint is available
    resp = Response(
        json.dumps(
            {
                "ok": True,
                "note": "Status endpoint - subscribe to navigator.state topic for real-time updates",
                "topic": TOPIC_NAVIGATOR_STATE,
            }
        ),
        mimetype="application/json",
    )
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


def api_navigator_return_home():
    """Start return to home sequence"""
    if request.method == "OPTIONS":
        resp = Response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
        return resp

    # Publish return to home command
    C.bus_pub(TOPIC_NAVIGATOR_RETURN_HOME_START, {"action": "return_home"}, add_ts=True)

    resp = Response(
        json.dumps({"ok": True, "action": "return_home"}),
        mimetype="application/json",
    )
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp
