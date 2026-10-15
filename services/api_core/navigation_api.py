"""Shared policy API; configuration has no actuator side effects."""

from flask import current_app, jsonify, request

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
    from services.navigation_trial import preparation_status

    preparation = preparation_status(target.with_name("navigation_trial_prepare.json"))
    last_trial = None
    try:
        trial_path = target.with_name("navigation_trial.json")
        if trial_path.stat().st_size <= 16384:
            trial = json.loads(trial_path.read_text())
            if (
                isinstance(trial, dict)
                and trial.get("mode") == "drive"
                and trial.get("running") is False
                and isinstance(trial.get("run_id"), str)
                and type(trial.get("observed_at")) in (int, float)
                and math.isfinite(trial["observed_at"])
                and 0 <= time.time() - trial["observed_at"]
            ):
                trial.pop("sampled_monotonic", None)
                last_trial = trial
    except (OSError, ValueError, TypeError):
        pass
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
        from services.navigation_trial import public_status

        row = public_status(row, fresh=fresh)
        return jsonify(
            {**row, "stale": not fresh, "age_s": age, "last_trial": last_trial, "preparation": preparation}
        ), 200
    except (OSError, ValueError, TypeError):
        return jsonify(
            {
                "running": False,
                "stale": True,
                "reason": "navigation_status_unavailable",
                "last_trial": last_trial,
                "preparation": preparation,
            }
        ), 200


def trial_handler():
    from services.navigation_trial import NavigationTrial, TrialError

    from .features_api import feature_manager

    key = "rider_navigation_trial"
    starter = current_app.extensions.get(key)
    if starter is None or starter.manager is not feature_manager:
        starter = NavigationTrial(feature_manager)
        current_app.extensions[key] = starter
    try:
        return jsonify(starter.start(request.get_json(silent=True))), 200
    except TrialError as exc:
        return jsonify({"ok": False, "error": exc.code, "details": exc.details}), exc.status
    except (OSError, ValueError):
        return jsonify({"ok": False, "error": "navigation_trial_prepare_failed"}), 503
