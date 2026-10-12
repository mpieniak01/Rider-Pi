"""Executor selection API; never starts a goal or changes operator arming."""

import json

from flask import Response, jsonify, request

from apps.compute.client import ComputeError
from services import compute_config
from services.compute_operations import execute


def config_handler():
    if request.method == "OPTIONS":
        return "", 204
    try:
        if request.method == "GET":
            return jsonify(compute_config.snapshot()), 200
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"executor_id", "revision"}:
            return jsonify({"error": "compute_configuration_invalid"}), 400
        data = compute_config.select(body["executor_id"], body["revision"])
        return jsonify(data), 200
    except ValueError as exc:
        error = str(exc)
        return jsonify({"error": error}), 409 if error in {
            "compute_configuration_conflict",
            "compute_stop_goals_first",
        } else 400
    except OSError:
        return jsonify({"error": "compute_persistence_failed"}), 503


def status_handler():
    try:
        return jsonify(compute_config.observed_status()), 200
    except (ValueError, OSError):
        return jsonify({"error": "compute_configuration_unavailable"}), 503


def task_handler(task):
    if request.content_length is None or not 0 < request.content_length <= 2 * 1024 * 1024:
        return jsonify({"error": "compute_input_size"}), 413
    try:
        raw = request.headers.get("X-Rider-Params", "{}")
        if len(raw) > 1024:
            raise ValueError("invalid")
        params = json.loads(raw)
        if not isinstance(params, dict) or set(params) - {"language", "prompt"}:
            raise ValueError("invalid")
        result, output = execute(task, request.get_data(), request.content_type or "", params)
        if output is not None:
            return Response(output, mimetype="audio/wav", headers={"Cache-Control": "no-store"})
        return jsonify(result), 200
    except ComputeError as exc:
        return jsonify({"error": exc.code}), exc.status if 400 <= exc.status <= 599 else 503
    except (ValueError, OSError):
        return jsonify({"error": "compute_configuration_or_input_invalid"}), 400
