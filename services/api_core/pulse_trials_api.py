"""Read-only trial catalog/status and one explicit Start through the normal gate."""

from flask import jsonify, request

from apps.motion.trial_profiles import PROFILES, VERSION, recipe
from services.control_commands import submit_control
from services.safety_contract import read_status


def catalog():
    state = read_status()
    return jsonify(
        {
            "version": VERSION,
            "supported": state.get("pulse_trials", {}).get("version") == VERSION and state.get("stale") is False,
            "profiles": list(PROFILES.values()),
            "direction": "forward",
            "max_run_ms": 1500,
        }
    )


def start():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "JSON object expected"}), 400
    try:
        recipe(data)
    except (ValueError, TypeError) as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    body, code = submit_control(data)
    return jsonify(body), code


def status(request_id):
    state = read_status()
    trials = state.get("pulse_trials", {})
    current = trials.get("current")
    if current and current.get("run_id") == request_id:
        return jsonify({"version": VERSION, "trial": current, "stale": state.get("stale", True)})
    previous = next((row for row in trials.get("history", []) if row.get("run_id") == request_id), None)
    if previous:
        return jsonify({"version": VERSION, "trial": previous, "stale": state.get("stale", True)})
    return jsonify({"ok": False, "error": "pulse_trial_not_found"}), 404
