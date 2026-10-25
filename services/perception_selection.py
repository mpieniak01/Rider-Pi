"""Persist only host model identity; never install weights or restart consumers."""

from __future__ import annotations

import copy
import json
import math
import os
import re
from pathlib import Path

from apps.motion import manual_settings
from services.compute_config import _lock, _selection_lock, _write
from services.safety_contract import read_status

# Wire identifiers, not an installed/available catalog. Venom owns that catalog.
MODEL_ENGINES = {
    "segformer-b0-ade20k": "segformer",
    "fast-scnn-floor": "segformer",
    "yolo26n-sem-ade20k": "segformer",
    "depth-anything-v2-indoor-small": "depth_plane",
}
IDENTITY_FIELDS = {"model_id", "artifact_sha256"}


def identity(perception):
    return tuple(perception.get(key, "") for key in ("model_id", "artifact_sha256"))


def validate_identity(perception):
    model, artifact = identity(perception)
    if not isinstance(model, str) or not isinstance(artifact, str):
        raise ValueError("navigation_model_identity_invalid")
    if not model and not artifact:
        return
    if model not in MODEL_ENGINES or not re.fullmatch(r"[a-f0-9]{64}", artifact):
        raise ValueError("navigation_model_identity_invalid")
    if perception.get("engine") != MODEL_ENGINES[model]:
        raise ValueError("navigation_model_engine_mismatch")


def drive_supported(perception):
    # All explicit semantic choices initially remain observation-only.
    model = perception.get("model_id", "")
    return not model or model == "depth-anything-v2-indoor-small"


def _zero_axes(row):
    return isinstance(row, dict) and all(
        type(row.get(key)) in (int, float) and math.isfinite(row[key]) and row[key] == 0 for key in ("lx", "az")
    )


def _require_executor_idle():
    safety = read_status(max_age_s=1.0)
    if (
        safety.get("state") not in {"DISARMED", "ESTOP"}
        or safety.get("ready") is not True
        or safety.get("stale") is not False
        or safety.get("owner") is not None
        or safety.get("can_move") is not False
        or safety.get("moving") is not False
        or safety.get("active_source") is not None
        or not isinstance(safety.get("generation"), str)
        or not safety["generation"]
        or not _zero_axes(safety.get("target"))
        or not _zero_axes(safety.get("output"))
    ):
        raise ValueError("navigation_model_requires_idle_disarmed")


def _require_goals_idle():
    from common.service_catalog import DEFAULT_REGISTRY, UNIT_CATALOG
    from services.core.goal_journal import boot_id

    path = Path(os.getenv("FEATURE_STATE_PATH", "/run/rider-motion/feature_state.json"))
    try:
        if path.stat().st_size > 256 * 1024:
            raise ValueError("oversized")
        state = json.loads(path.read_text())
        requested = state["requested"]
        active = state["active"]
        journal = state["ownership_journal"]
        if (
            not isinstance(requested, list)
            or not isinstance(active, list)
            or not isinstance(journal, dict)
            or journal.get("boot_id") != boot_id()
            or not journal.get("boot_id")
            or any(not isinstance(name, str) or name not in DEFAULT_REGISTRY for name in requested + active)
        ):
            raise ValueError("invalid")
        names = set(requested + active)
        admin = journal.get("admin", [])
        if not isinstance(admin, list) or any(unit not in UNIT_CATALOG for unit in admin):
            raise ValueError("invalid")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ValueError("navigation_goal_state_unavailable") from exc
    if (
        names & {"s14_venom_navigation", "s15_venom_perception"}
        or any(DEFAULT_REGISTRY[name].can_move for name in names)
        or any(UNIT_CATALOG[unit].get("can_move") for unit in admin)
    ):
        # Stop the loop explicitly; camera-only consumers may remain active.
        raise ValueError("navigation_model_stop_loops_first")


def require_idle():
    """Called with task selection and executor/settings mutexes already held."""
    _require_executor_idle()
    _require_goals_idle()


def _reset_approval(config):
    config.update(mode="observe", verified=False, calibration_id="", model_sha256="")
    config["avoidance"] = {**config["avoidance"], "sweep_verified": False}


def _observe_unapproved(config):
    return (
        config["mode"] == "observe"
        and config["verified"] is False
        and config["calibration_id"] == ""
        and config["model_sha256"] == ""
        and config["avoidance"]["sweep_verified"] is False
    )


def select(body):
    """Host commits a qualified identity with CAS; replay never restores ARM."""
    from services import navigation_config

    if (
        not isinstance(body, dict)
        or set(body) != {"revision", "model_id", "artifact_sha256", "engine"}
        or type(body["revision"]) is not int
        or body["revision"] < 0
    ):
        raise ValueError("navigation_model_selection_invalid")
    validate_identity(body)
    if not body["model_id"]:
        raise ValueError("navigation_model_selection_invalid")
    # Feature start/preparation uses selection_lock. The sole executor already
    # shares manual_settings.locked for non-STOP commands and never waits on it.
    # Therefore ARM cannot race this short read/atomic-write transaction.
    with _selection_lock(), manual_settings.locked(blocking=False), _lock(navigation_config.path()):
        current = navigation_config.snapshot()
        same = identity(current["perception"]) == identity(body)
        if body["revision"] != current["revision"]:
            if same and body["revision"] + 1 == current["revision"] and _observe_unapproved(current):
                return current
            raise ValueError("navigation_configuration_conflict")
        require_idle()
        if same and _observe_unapproved(current):
            return current
        result = copy.deepcopy(current)
        result["perception"].update({key: body[key] for key in ("engine", "model_id", "artifact_sha256")})
        if body["model_id"] == "depth-anything-v2-indoor-small":
            from services.model_input import default_input_region

            avoidance = result.get("avoidance", {})
            if not (avoidance.get("enabled") and avoidance.get("geometry", {}).get("mode") == "ground"):
                result["perception"].setdefault("input_region", default_input_region(result["corridor"]))
        else:
            result["perception"].pop("input_region", None)
        result["revision"] += 1
        _reset_approval(result)
        # Semantic selections cannot retain enabled depth-only avoidance.
        if body["engine"] != "depth_plane":
            result["avoidance"]["enabled"] = False
        navigation_config.validate(result)
        _write(navigation_config.path(), result)
        return result


def revoke_approval_locked():
    """Shared task/executor locks are held; failed provider change stays safe."""
    from services import navigation_config

    with _lock(navigation_config.path()):
        current = navigation_config.snapshot()
        if _observe_unapproved(current):
            return
        result = copy.deepcopy(current)
        _reset_approval(result)
        result["revision"] += 1
        _write(navigation_config.path(), navigation_config.validate(result))
