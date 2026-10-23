"""Shared policy API; configuration has no actuator side effects."""

from flask import current_app, jsonify, request

from services import navigation_config


def _present_config(config):
    from services.camera_pipeline_store import snapshot as camera_configuration
    from services.navigation_profiles import catalog
    from services.perception_tuning import presentation

    eligible = camera_configuration()["profile"]["analysis_location"] == "venom"
    behavior = catalog(config.get("behavior"), config.get("perception"))
    behavior.update(execution_eligible=eligible, reason="" if eligible else "navigation_profile_local_executor")
    return {
        **config,
        "behavior_catalog": behavior,
        "model_tuning_supported": True,
        "perception_tuning": presentation(config),
    }


def config_handler():
    try:
        if request.method == "GET":
            config = navigation_config.snapshot()
            return jsonify(_present_config(config)), 200
        data = navigation_config.configure(request.get_json(silent=True))
        return jsonify({"ok": True, "persisted": True, "config": _present_config(data)}), 200
    except ValueError as exc:
        code = str(exc)
        return jsonify({"error": code}), 409 if code in {
            "navigation_configuration_conflict",
            "navigation_profile_requires_stopped",
            "navigation_profile_local_executor",
            "compute_stop_goals_first",
            "navigation_stop_goals_first",
            "navigation_model_selection_required",
            "navigation_model_requires_idle_disarmed",
            "navigation_model_stop_loops_first",
        } else 400
    except BlockingIOError:
        return jsonify({"error": "navigation_profile_busy"}), 409
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
                from services.navigation_trial import public_status

                last_trial = public_status(trial, fresh=False)
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
    from services.navigation_trial import NavigationTrial

    return _start_handler(NavigationTrial, "rider_navigation_trial")


def journey_handler():
    from services.navigation_journey import NavigationJourney

    return _start_handler(NavigationJourney, "rider_navigation_journey")


def _start_handler(starter_class, key):
    from services.navigation_trial import TrialError

    from .features_api import feature_manager

    starter = current_app.extensions.get(key)
    if starter is None or starter.manager is not feature_manager:
        starter = starter_class(feature_manager)
        current_app.extensions[key] = starter
    try:
        result = starter.start(request.get_json(silent=True))
        from .http_contract import operation

        operation(
            {
                "request_id": result["request_id"],
                "action": "start",
                "target": "s14_venom_navigation",
                "status": "executed",
                "confirmed": True,
                "ack_kind": "navigation_running",
                "ack": None,
                "actuation": False,
                "physical_completion": "unverified",
            }
        )
        return jsonify(result), 200
    except TrialError as exc:
        return jsonify({"ok": False, "error": exc.code, "details": exc.details}), exc.status
    except (OSError, ValueError):
        return jsonify({"ok": False, "error": "navigation_trial_prepare_failed"}), 503


def _model_response(action):
    from apps.compute.client import ComputeError

    try:
        response = jsonify(action())
        response.headers["Cache-Control"] = "no-store"
        return response, 200
    except ComputeError as exc:
        return jsonify({"error": exc.code}), exc.status if 400 <= exc.status <= 599 else 503
    except (BlockingIOError, TimeoutError):
        return jsonify({"error": "navigation_model_selection_busy"}), 409
    except ValueError as exc:
        code = str(exc)
        conflict = {
            "navigation_configuration_conflict",
            "navigation_model_requires_idle_disarmed",
            "navigation_model_stop_loops_first",
        }
        unavailable = {"navigation_goal_state_unavailable"}
        return jsonify({"error": code}), 503 if code in unavailable else 409 if code in conflict else 400
    except OSError:
        return jsonify({"error": "navigation_model_unavailable"}), 503


def models_handler():
    from services.perception_proxy import catalog

    return _model_response(catalog)


def model_handler():
    from services.perception_proxy import choose

    return _model_response(lambda: choose(request.get_json(silent=True)))


def model_selection_handler():
    from services.perception_selection import select

    return _model_response(lambda: {"ok": True, "persisted": True, "config": select(request.get_json(silent=True))})


def local_models_handler():
    from services.perception_local import catalog

    from .camera_pipeline_api import _pipeline

    return _model_response(lambda: catalog(_pipeline().status()))
