#!/usr/bin/env python3
"""Sterowanie wyłącznie przez wspólną bramę; historia nie jest ACK hardware."""

from __future__ import annotations

import time

from flask import Response, jsonify, request

from services.control_commands import submit_control
from services.safety_contract import read_status

from . import compat as C


def _response(body, code=200):
    response = jsonify({**body, "server_time": time.time()})
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response, code


def _payload():
    data = request.get_json(silent=True)
    if data is None:
        data = request.args.to_dict()
    if not isinstance(data, dict):
        raise ValueError("JSON object expected")
    return data


def _submit(overrides=None):
    if request.method == "OPTIONS":
        return Response("", 204)
    try:
        data = _payload()
        data.update(overrides or {})
        if request.method != "POST":
            error = "stop_requires_post" if data.get("action") == "stop" else "actuator_requires_post_with_generation"
            response, code = _response({"ok": False, "error": error}, 405)
            response.headers["Allow"] = "POST, OPTIONS"
            return response, code
    except ValueError as exc:
        return _response({"ok": False, "error": str(exc)}, 400)
    body, code = submit_control(data)
    C.motion_queue_append(
        {
            "source": data.get("source", "manual"),
            "status": "confirmed" if body.get("confirmed") else "pending" if code == 202 else "rejected",
            "action": data.get("action", data.get("cmd")),
            "request_id": body.get("request_id"),
            "reason": body.get("error"),
            "ts": time.time(),
        }
    )
    return _response(body, code)


def api_move():
    if request.method == "GET":
        return _response({"ok": False, "error": "actuator_requires_post_with_generation"}, 405)
    return _submit({"action": "move"})


def api_stop():
    return _submit({"action": "stop"})


def api_preset():
    return _submit({"action": "action"})


def api_voice():
    data = _payload()
    C.bus_pub("cmd.voice", {"text": data.get("text", ""), "ts": time.time()})
    return _response({"ok": True, "physical_completion": "not_applicable"})


def api_cmd():
    return _submit()


def api_balance():
    return _submit({"action": "balance"})


def api_height():
    return _submit({"action": "height"})


def api_control():
    return _submit()


def api_safety():
    if request.method == "GET":
        return _response({"ok": True, "safety": read_status()})
    if request.method == "OPTIONS":
        return Response("", 204)
    try:
        data = _payload()
    except ValueError as exc:
        return _response({"ok": False, "error": str(exc)}, 400)
    if data.get("action") not in {"arm", "disarm", "estop", "clear_estop", "stop"}:
        return _response({"ok": False, "error": "invalid safety action"}, 400)
    return _submit()


def api_control_state():
    if request.method == "OPTIONS":
        return Response("", 204)
    safety = read_status()
    ack = safety.get("last_ack") or {}
    actuator_state = safety.get("actuators") or {}
    return _response(
        {
            "ok": True,
            "safety": safety,
            "balance": actuator_state.get("balance", {"enabled": None, "ts": None}),
            "height": actuator_state.get("height", {"value": None, "ts": None}),
            "tracking": dict(C.LAST_TRACKING_MODE),
            "navigator": dict(C.LAST_NAVIGATOR),
            "ack": ack,
            "observed_at": safety.get("observed_at"),
        }
    )


def api_motion_queue():
    if request.method == "OPTIONS":
        return Response("", 204)
    return _response(
        {
            "ok": True,
            "kind": "request_history",
            "items": C.motion_queue_snapshot(limit=10),
            "generated_at": time.time(),
            "ack": read_status().get("last_ack"),
        }
    )
