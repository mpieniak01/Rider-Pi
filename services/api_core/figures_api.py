"""Read-only own-figure catalog/status; Start uses the existing permission gate."""

from flask import jsonify, request

from apps.motion.figure_recipes import catalog as recipes, validate_request
from services.control_commands import submit_control
from services.safety_contract import read_status


def catalog():
    state = read_status()
    figures = state.get("figures", {})
    return jsonify(
        {**recipes(figures.get("axes")), "supported": (figures.get("version") == 1 and state.get("stale") is False)}
    )


def start():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "JSON object expected"}), 400
    try:
        validate_request(body)
    except (ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    result, code = submit_control(body)
    return jsonify(result), code


def status(request_id):
    state = read_status()
    figures = state.get("figures", {})
    rows = [figures.get("current")] + figures.get("history", [])
    run = next((row for row in rows if row and row.get("run_id") == request_id), None)
    if run is None:
        return jsonify({"ok": False, "error": "figure_run_not_found"}), 404
    return jsonify({"version": 1, "run": run, "stale": state.get("stale", True)})


def cancel(request_id):
    state = read_status()
    current = state.get("figures", {}).get("current")
    if not current or current.get("run_id") != request_id or current.get("phase") not in {"preparing", "running"}:
        return jsonify({"ok": False, "error": "figure_run_inactive"}), 409
    result, code = submit_control({"action": "stop", "expected_generation": current["generation"]})
    return jsonify(result), code
