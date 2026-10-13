"""Shared policy API; configuration has no actuator side effects."""

from flask import jsonify, request

from services import navigation_config


def config_handler():
    try:
        if request.method == "GET":
            return jsonify(navigation_config.snapshot()), 200
        data = navigation_config.configure(request.get_json(silent=True))
        return jsonify({"ok": True, "persisted": True, "config": data}), 200
    except ValueError as exc:
        code = str(exc)
        return jsonify({"error": code}), 409 if code in {
            "navigation_configuration_conflict",
            "compute_stop_goals_first",
            "navigation_stop_goals_first",
        } else 400
    except OSError:
        return jsonify({"error": "navigation_persistence_failed"}), 503


def status_handler():
    import json
    import math
    import os
    import time
    from pathlib import Path

    target = Path(os.getenv("RIDER_NAVIGATION_STATUS", "/run/rider-motion/navigation_loop.json"))
    try:
        if target.stat().st_size > 16384:
            raise ValueError("oversized")
        row = json.loads(target.read_text())
        if not isinstance(row, dict):
            raise ValueError("invalid")
        observed = row.get("observed_at")
        age = time.time() - observed if type(observed) in (int, float) else None
        fresh = age is not None and math.isfinite(age) and 0 <= age <= 1.0
        if age is not None and not math.isfinite(age):
            raise ValueError("invalid_age")
        return jsonify({**row, "stale": not fresh, "age_s": age}), 200
    except (OSError, ValueError, TypeError):
        return jsonify({"running": False, "stale": True, "reason": "navigation_status_unavailable"}), 200
