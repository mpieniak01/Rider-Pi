#!/usr/bin/env python3
"""HTTP compatibility entry: canonical commands only, never a second SDK owner."""

from __future__ import annotations

import os

from flask import Flask, jsonify, request

from services.api_core.http_contract import install
from services.api_core.http_security import apply_cors
from services.control_commands import submit_control
from services.safety_contract import read_status

app = Flask(__name__)
install(app, after_request=True)


@app.after_request
def _add_cors(response):
    apply_cors(response)
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Accept"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"ok": True, "safety": read_status()})


def _submit(overrides=None):
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(silent=True)
    if data is None:
        data = request.args.to_dict()
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "JSON object expected"}), 400
    data.update(overrides or {})
    body, code = submit_control(data)
    return jsonify(body), code


@app.route("/control", methods=["POST", "OPTIONS"])
def control_post():
    return _submit()


@app.route("/api/move", methods=["GET", "POST", "OPTIONS"])
def api_move():
    if request.method not in {"POST", "OPTIONS"}:
        return jsonify({"ok": False, "error": "actuator_requires_post_with_generation"}), 405
    return _submit({"action": "move"})


@app.route("/api/stop", methods=["GET", "POST", "OPTIONS"])
def api_stop():
    if request.method not in {"POST", "OPTIONS"}:
        response = jsonify({"ok": False, "error": "stop_requires_post"})
        response.headers["Allow"] = "POST, OPTIONS"
        return response, 405
    return _submit({"action": "stop"})


@app.route("/api/balance", methods=["GET", "POST", "OPTIONS"])
def api_balance():
    if request.method not in {"POST", "OPTIONS"}:
        return jsonify({"ok": False, "error": "actuator_requires_post_with_generation"}), 405
    return _submit({"action": "balance"})


@app.route("/api/height", methods=["GET", "POST", "OPTIONS"])
def api_height():
    if request.method not in {"POST", "OPTIONS"}:
        return jsonify({"ok": False, "error": "actuator_requires_post_with_generation"}), 405
    return _submit({"action": "height"})


if __name__ == "__main__":
    app.run(host=os.getenv("WEB_HOST", "127.0.0.1"), port=int(os.getenv("WEB_PORT", "8081")), threaded=True)
