"""One device-owned persisted policy; saving never starts a service."""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

from services.compute_config import _lock, _require_idle_goals, _selection_lock, _write

DEFAULT = {
    "protocol_version": 1,
    "revision": 0,
    "mode": "observe",
    "speed": 0.1,
    "decision_budget_ms": 300,
    "max_motion_ms": 150,
    "corridor": [0.35, 0.80, 0.65, 0.95],
    "perception": {"engine": "segformer", "residual_limit": 0.06, "outlier_limit": 0.005, "slope_min": 2.0},
    "verified": False,
    "calibration_id": "",
    "model_sha256": "",
}


def path():
    return Path(os.getenv("RIDER_NAVIGATION_CONFIG", "data/navigation_config.json"))


def validate(data):
    if not isinstance(data, dict) or set(data) != set(DEFAULT):
        raise ValueError("navigation_configuration_invalid")
    if (
        type(data["protocol_version"]) is not int
        or data["protocol_version"] != 1
        or type(data["revision"]) is not int
        or data["revision"] < 0
    ):
        raise ValueError("navigation_configuration_invalid")
    if (
        not isinstance(data["mode"], str)
        or data["mode"] not in {"observe", "drive"}
        or type(data["verified"]) is not bool
    ):
        raise ValueError("navigation_configuration_invalid")
    speed = data["speed"]
    if (
        isinstance(speed, bool)
        or not isinstance(speed, (float, int))
        or not math.isfinite(speed)
        or not 0 < speed <= 0.15
    ):
        raise ValueError("navigation_speed_invalid")
    if type(data["decision_budget_ms"]) is not int or not 100 <= data["decision_budget_ms"] <= 500:
        raise ValueError("navigation_deadline_invalid")
    if type(data["max_motion_ms"]) is not int or not 50 <= data["max_motion_ms"] <= 200:
        raise ValueError("navigation_duration_invalid")
    roi = data["corridor"]
    if (
        not isinstance(roi, list)
        or len(roi) != 4
        or any(type(v) not in (float, int) or not math.isfinite(v) for v in roi)
    ):
        raise ValueError("navigation_corridor_invalid")
    x0, y0, x1, y1 = roi
    if not 0 <= x0 < x1 <= 1 or not 0 <= y0 < y1 <= 1:
        raise ValueError("navigation_corridor_invalid")
    if not isinstance(data["calibration_id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{0,64}", data["calibration_id"]):
        raise ValueError("navigation_calibration_invalid")
    if not isinstance(data["model_sha256"], str) or not re.fullmatch(r"(?:[a-f0-9]{64})?", data["model_sha256"]):
        raise ValueError("navigation_model_invalid")
    if data["mode"] == "drive" and (not data["verified"] or not data["calibration_id"] or not data["model_sha256"]):
        raise ValueError("navigation_validation_required")
    perception = data["perception"]
    if not isinstance(perception, dict) or set(perception) != set(DEFAULT["perception"]):
        raise ValueError("navigation_perception_invalid")
    if not isinstance(perception["engine"], str) or perception["engine"] not in {"segformer", "depth_plane"}:
        raise ValueError("navigation_perception_invalid")
    for key, low, high in (("residual_limit", 0.01, 0.15), ("outlier_limit", 0.0, 0.02), ("slope_min", 1.0, 4.0)):
        value = perception[key]
        if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError("navigation_perception_invalid")
    return data


def snapshot():
    p = path()
    if not p.exists():
        return json.loads(json.dumps(DEFAULT))
    if p.stat().st_size > 4096:
        raise ValueError("navigation_configuration_invalid")
    data = json.loads(p.read_text())
    if isinstance(data, dict) and "perception" not in data:
        data["perception"] = dict(DEFAULT["perception"])
    return validate(data)


def configure(body):
    with _selection_lock():
        return configure_locked(body)


def configure_locked(body):
    """Caller already holds the shared feature selection transaction."""
    if (
        not isinstance(body, dict)
        or set(body) != {"revision", "values"}
        or type(body["revision"]) is not int
        or not isinstance(body["values"], dict)
    ):
        raise ValueError("navigation_configuration_invalid")
    if set(body["values"]) - (set(DEFAULT) - {"protocol_version", "revision"}):
        raise ValueError("navigation_configuration_invalid")
    with _lock(path()):
        old = snapshot()
        if body["revision"] != old["revision"]:
            raise ValueError("navigation_configuration_conflict")
        # Mode switches do not change compute selection or model parameters.
        # Unrelated voice/compute consumers can continue using their own policy.
        if set(body["values"]) != {"mode"}:
            _require_idle_goals()
        state_path = Path(os.getenv("FEATURE_STATE_PATH", "/run/rider-motion/feature_state.json"))
        if state_path.exists():
            try:
                if state_path.stat().st_size > 256 * 1024:
                    raise ValueError("oversized")
                requested = json.loads(state_path.read_text()).get("requested", [])
                if not isinstance(requested, list) or any(not isinstance(name, str) for name in requested):
                    raise ValueError("invalid")
            except (ValueError, OSError, AttributeError) as exc:
                raise ValueError("navigation_goal_state_unavailable") from exc
            if set(requested) & {"s14_venom_navigation", "s15_venom_perception"}:
                raise ValueError("navigation_stop_goals_first")
        proposed = {**old, **body["values"], "revision": old["revision"] + 1}
        changed = any(
            proposed[k] != old[k]
            for k in ("speed", "corridor", "model_sha256", "decision_budget_ms", "max_motion_ms", "perception")
        )
        if (
            old["verified"]
            and changed
            and (proposed["calibration_id"] == old["calibration_id"] or body["values"].get("verified") is not True)
        ):
            proposed.update(verified=False, mode="observe")
        data = validate(proposed)
        _write(path(), data)
    return data
