"""Shared policy API; configuration has no actuator side effects."""

from flask import jsonify, request

from services import navigation_config


def config_handler():
    try:
        if request.method == "GET":
            return jsonify(navigation_config.snapshot()), 200
        return jsonify(navigation_config.configure(request.get_json(silent=True))), 200
    except ValueError as exc:
        code = str(exc)
        return jsonify({"error": code}), 409 if code in {
            "navigation_configuration_conflict",
            "compute_stop_goals_first",
        } else 400
    except OSError:
        return jsonify({"error": "navigation_persistence_failed"}), 503
