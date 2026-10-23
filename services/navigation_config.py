"""One device-owned persisted policy; saving never starts a service."""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

from services.compute_config import _lock, _require_idle_goals, _selection_lock, _write
from services.navigation_profiles import DEFAULT_BEHAVIOR, validate_behavior
from services.perception_selection import IDENTITY_FIELDS, drive_supported, identity, validate_identity

DEFAULT = {
    "protocol_version": 1,
    "revision": 0,
    "behavior": dict(DEFAULT_BEHAVIOR),
    "mode": "observe",
    "speed": 0.1,
    "decision_budget_ms": 300,
    "max_motion_ms": 150,
    "corridor": [0.35, 0.80, 0.65, 0.95],
    "perception": {"engine": "segformer", "residual_limit": 0.06, "outlier_limit": 0.005, "slope_min": 2.0},
    "avoidance": {
        "protocol_version": 3,
        "enabled": False,
        "sweep_verified": False,
        "mirrored": False,
        "turn_speed": 0.05,
        "turn_ms": 100,
        "max_turn_pulses": 3,
        "max_stalled_corrections": 2,
        "progress_min_delta": 0.03,
        "geometry": {
            "mode": "ground",
            "fx": None,
            "fy": None,
            "cx": 0.5,
            "cy": 0.5,
            "radius_ratio": None,
            "lookahead_ratio": 2.0,
            "max_heading_deg": 45.0,
        },
    },
    "verified": False,
    "calibration_id": "",
    "model_sha256": "",
}


def path():
    return Path(os.getenv("RIDER_NAVIGATION_CONFIG", "data/navigation_config.json"))


def _validate_command_policy(data):
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


def _validated_perception(perception):
    required = set(DEFAULT["perception"])
    if (
        not isinstance(perception, dict)
        or not required <= set(perception)
        or set(perception) - required - IDENTITY_FIELDS
    ):
        raise ValueError("navigation_perception_invalid")
    validate_identity(perception)
    if not isinstance(perception["engine"], str) or perception["engine"] not in {"segformer", "depth_plane"}:
        raise ValueError("navigation_perception_invalid")
    for key, low, high in (("residual_limit", 0.01, 0.15), ("outlier_limit", 0.0, 0.02), ("slope_min", 1.0, 4.0)):
        value = perception[key]
        if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError("navigation_perception_invalid")
    return perception


def _validate_correction_limits(avoidance):
    if type(avoidance["max_stalled_corrections"]) is not int or not 1 <= avoidance["max_stalled_corrections"] <= 5:
        raise ValueError("navigation_avoidance_invalid")
    delta = avoidance["progress_min_delta"]
    if type(delta) not in (int, float) or not math.isfinite(delta) or not 0 <= delta <= 0.3:
        raise ValueError("navigation_avoidance_invalid")


def _validated_avoidance(avoidance):
    if not isinstance(avoidance, dict) or set(avoidance) != set(DEFAULT["avoidance"]):
        raise ValueError("navigation_avoidance_invalid")
    if type(avoidance["protocol_version"]) is not int or avoidance["protocol_version"] not in (2, 3):
        raise ValueError("navigation_avoidance_invalid")
    for key in ("enabled", "sweep_verified", "mirrored"):
        if type(avoidance[key]) is not bool:
            raise ValueError("navigation_avoidance_invalid")
    if (
        type(avoidance["turn_speed"]) not in (float, int)
        or not math.isfinite(avoidance["turn_speed"])
        or not 0.01 <= avoidance["turn_speed"] <= 0.1
    ):
        raise ValueError("navigation_avoidance_invalid")
    for key, low, high in (("turn_ms", 50, 150), ("max_turn_pulses", 1, 5)):
        if type(avoidance[key]) is not int or not low <= avoidance[key] <= high:
            raise ValueError("navigation_avoidance_invalid")
    _validate_correction_limits(avoidance)
    return avoidance


def _validated_geometry(geometry):
    if not isinstance(geometry, dict) or set(geometry) != set(DEFAULT["avoidance"]["geometry"]):
        raise ValueError("navigation_geometry_invalid")
    if geometry["mode"] not in ("ground", "image"):
        raise ValueError("navigation_geometry_invalid")
    for key, low, high in (
        ("fx", 0.1, 5.0),
        ("fy", 0.1, 5.0),
        ("cx", 0.0, 1.0),
        ("cy", 0.0, 1.0),
        ("radius_ratio", 0.05, 5.0),
        ("lookahead_ratio", 0.25, 8.0),
        ("max_heading_deg", 5.0, 70.0),
    ):
        value = geometry[key]
        if value is None and key in {"fx", "fy", "radius_ratio"}:
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError("navigation_geometry_invalid")
    return geometry


def _validate_avoidance_authority(data, perception, avoidance, geometry):
    if (
        avoidance["enabled"]
        and avoidance["protocol_version"] == 3
        and geometry["mode"] == "ground"
        and data["mode"] == "drive"
        and any(geometry[key] is None for key in ("fx", "fy", "radius_ratio"))
    ):
        raise ValueError("navigation_geometry_calibration_required")
    if avoidance["enabled"] and (
        perception["engine"] != "depth_plane" or data["speed"] > 0.1 or data["max_motion_ms"] > 150
    ):
        raise ValueError("navigation_avoidance_limits")
    if avoidance["enabled"] and data["mode"] == "drive" and not avoidance["sweep_verified"]:
        raise ValueError("navigation_avoidance_not_accepted")


def validate(data):
    if isinstance(data, dict) and "behavior" not in data:
        data = {**data, "behavior": dict(DEFAULT_BEHAVIOR)}
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
    validate_behavior(data["behavior"])
    _validate_command_policy(data)
    if not isinstance(data["calibration_id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{0,64}", data["calibration_id"]):
        raise ValueError("navigation_calibration_invalid")
    if not isinstance(data["model_sha256"], str) or not re.fullmatch(r"(?:[a-f0-9]{64})?", data["model_sha256"]):
        raise ValueError("navigation_model_invalid")
    if data["mode"] == "drive" and (not data["verified"] or not data["calibration_id"] or not data["model_sha256"]):
        raise ValueError("navigation_validation_required")
    perception = _validated_perception(data["perception"])
    if data["mode"] == "drive":
        if not drive_supported(perception):
            raise ValueError("navigation_model_observe_only")
        if perception.get("model_id") and data["model_sha256"] != perception.get("artifact_sha256"):
            raise ValueError("navigation_model_approval_mismatch")
    avoidance = _validated_avoidance(data["avoidance"])
    geometry = _validated_geometry(avoidance["geometry"])
    _validate_avoidance_authority(data, perception, avoidance, geometry)
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
    if isinstance(data, dict) and "avoidance" not in data:
        data["avoidance"] = json.loads(json.dumps(DEFAULT["avoidance"]))
    if (
        isinstance(data, dict)
        and isinstance(data.get("avoidance"), dict)
        and "protocol_version" not in data["avoidance"]
    ):
        data["avoidance"]["protocol_version"] = 2
    if isinstance(data, dict) and isinstance(data.get("avoidance"), dict):
        avoidance = data["avoidance"]
        avoidance.setdefault("max_stalled_corrections", 2)
        avoidance.setdefault("progress_min_delta", 0.03)
        if "geometry" not in avoidance:
            avoidance["geometry"] = {**DEFAULT["avoidance"]["geometry"], "mode": "image"}
    return validate(data)


def configure(body):
    with _selection_lock():
        return configure_locked(body)


def _require_navigation_goals_stopped():
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
        _require_navigation_goals_stopped()
        proposed = {**old, **body["values"], "revision": old["revision"] + 1}
        # Model identities are committed by the host-coordinated endpoint only.
        proposed_perception = proposed.get("perception")
        _validated_perception(proposed_perception)
        if identity(proposed_perception) != identity(old["perception"]):
            raise ValueError("navigation_model_selection_required")
        behavior = validate_behavior(proposed.get("behavior"))
        profile_changed = behavior != old.get("behavior", DEFAULT_BEHAVIOR)
        if profile_changed:
            from services.navigation_behavior import require_stopped

            require_stopped()
            proposed.update(mode="observe", verified=False, calibration_id="", model_sha256="")
            proposed["avoidance"] = {**proposed["avoidance"], "sweep_verified": False}
        engine_changed = proposed_perception["engine"] != old["perception"]["engine"]
        if engine_changed and proposed_perception.get("model_id"):
            raise ValueError("navigation_model_selection_required")
        changed = any(
            proposed[k] != old[k]
            for k in (
                "speed",
                "corridor",
                "model_sha256",
                "decision_budget_ms",
                "max_motion_ms",
                "perception",
                "avoidance",
                "behavior",
            )
        )
        if (
            old["verified"]
            and changed
            and (proposed["calibration_id"] == old["calibration_id"] or body["values"].get("verified") is not True)
        ):
            proposed.update(verified=False, mode="observe")
        if engine_changed:
            from apps.motion import manual_settings
            from services.perception_selection import _reset_approval, require_idle

            with manual_settings.locked(blocking=False):
                require_idle()
                _reset_approval(proposed)
                data = validate(proposed)
                _write(path(), data)
        else:
            data = validate(proposed)
            _write(path(), data)
    return data
