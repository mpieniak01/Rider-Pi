"""Navigation control requires the executor's current operator authorization."""

from __future__ import annotations

import json
import math
import time

from flask import Response, request

from apps.navigator.safety import authorize_request
from common.bus import TOPIC_NAVIGATOR_RETURN_HOME_START
from services.safety_contract import read_status, request_stop

from . import compat as C
from .http_security import apply_cors
from .navigation_state import snapshot as navigation_snapshot

TOPIC_NAVIGATOR_CONTROL = "navigator.control"
TOPIC_NAVIGATOR_STATE = "navigator.state"


def _response(body, status=200):
    response = Response(json.dumps(body), status=status, mimetype="application/json")
    apply_cors(response)
    return response


def _start(action, topic):
    if request.method == "OPTIONS":
        return _response({}, 204)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _response({"ok": False, "error": "JSON object expected"}, 400)
    if action == "start" and payload.get("strategy", "STOP") not in {"STOP", "AVOID"}:
        return _response({"ok": False, "error": "invalid strategy"}, 400)
    try:
        envelope, safety = authorize_request(payload)
    except (ValueError, TypeError, OverflowError) as exc:
        return _response({"ok": False, "error": str(exc), "safety": read_status()}, 409)
    envelope.update(action=action, strategy=payload.get("strategy", "STOP"))
    try:
        C.bus_pub(topic, envelope, add_ts=False)
    except Exception as exc:
        return _response({"ok": False, "error": str(exc)}, 503)
    return _response(
        {
            "ok": False,
            "pending": True,
            "confirmed": False,
            "request_id": envelope["request_id"],
            "action": action,
            "safety": safety,
        },
        202,
    )


def api_navigator_start():
    return _start("start", TOPIC_NAVIGATOR_CONTROL)


def api_navigator_return_home():
    return _start("return_home", TOPIC_NAVIGATOR_RETURN_HOME_START)


def api_navigator_stop():
    if request.method == "OPTIONS":
        return _response({}, 204)
    result = request_stop(owner="navigation")
    C.bus_pub(TOPIC_NAVIGATOR_CONTROL, {"action": "stop", "ts": time.time()})
    return _response(result, 200 if result["ok"] else 202 if result.get("pending") else 503)


def api_navigator_config():
    if request.method == "OPTIONS":
        return _response({}, 204)
    safety = read_status()
    if safety.get("state") != "DISARMED":
        return _response({"ok": False, "error": "configure_only_when_disarmed", "safety": safety}, 409)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _response({"ok": False, "error": "JSON object expected"}, 400)
    config = {}
    try:
        if "strategy" in data:
            if data["strategy"] not in {"STOP", "AVOID"}:
                raise ValueError("invalid strategy")
            config["strategy"] = data["strategy"]
        for name in ("fwd_speed", "turn_speed"):
            if name in data:
                value = float(data[name])
                if isinstance(data[name], bool) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("invalid " + name)
                config[name] = value
    except (ValueError, TypeError) as exc:
        return _response({"ok": False, "error": str(exc)}, 400)
    C.bus_pub(TOPIC_NAVIGATOR_CONTROL, {"action": "config", "config": config, "ts": time.time()})
    return _response({"ok": False, "pending": True, "confirmed": False, "action": "config"}, 202)


def api_navigator_status():
    status = dict(C.LAST_NAVIGATOR)
    observed = status.get("observed_at", status.get("ts"))
    age = time.time() - observed if type(observed) in (float, int) and math.isfinite(observed) else None
    status.update(
        observed_at=observed,
        stale=status.get("stale") is True or age is None or age < -0.1 or age > 3,
        safety=read_status(),
        navigation=navigation_snapshot(),
        planning_request_available=False,
        planning_unavailable_reason="passive_plan_request_unavailable",
        navigation_actuation_available=False,
        navigation_block_reason="navigation_traversal_unverified",
        physical_completion="unverified",
    )
    return _response(status)
