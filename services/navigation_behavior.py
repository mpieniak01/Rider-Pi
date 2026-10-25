"""Stopped-only profile changes and independent temporal decision checks."""

from __future__ import annotations

import math

from services.navigation_profiles import DEFAULT_BEHAVIOR, parameters, policy_digest, validate_behavior


def require_stopped():
    from services.safety_contract import read_status

    row = read_status(max_age_s=1.0)
    if (
        row.get("state") not in {"ARMED", "DISARMED", "ESTOP"}
        or row.get("ready") is not True
        or row.get("stale") is not False
        or row.get("moving") is not False
        or any(
            not isinstance(row.get(field), dict)
            or any(
                type(row[field].get(axis)) not in (int, float)
                or not math.isfinite(row[field][axis])
                or row[field][axis] != 0
                for axis in ("lx", "az")
            )
            for field in ("target", "output")
        )
    ):
        raise ValueError("navigation_profile_requires_stopped")


def active(config):
    return config.get("behavior", DEFAULT_BEHAVIOR).get("profile_id") != "legacy"


def _legacy_reply_valid(decision):
    if "behavior" in decision:
        try:
            if validate_behavior(decision["behavior"]) != DEFAULT_BEHAVIOR:
                return False
        except ValueError:
            return False
    return decision.get("action") != "slow"


def _temporal_evidence_valid(temporal, decision):
    if not isinstance(temporal, dict) or temporal.get("version") != 1 or type(temporal["version"]) is not int:
        return False
    steering = decision.get("action") in {"turn_left", "turn_right", "steer_left", "steer_right"}
    if temporal.get("action") != decision.get("action") and not steering:
        return False
    if temporal.get("near_guard_clear") is not True:
        return False
    frames = temporal.get("evidence_frames")
    if type(frames) is not int or not 3 <= frames <= 64:
        return False
    factor = temporal.get("speed_factor")
    return type(factor) in (int, float) and math.isfinite(factor)


def _temporal_action_valid(config, expected, decision, temporal):
    steering = decision.get("action") in {"turn_left", "turn_right", "steer_left", "steer_right"}
    factor = temporal["speed_factor"]
    if decision.get("action") == "slow":
        return (
            temporal.get("risk") == "caution"
            and factor == parameters(expected, config.get("perception"))["slow_speed_factor"]
            and decision.get("state") in {"clear", "obstacle", "unknown"}
        )
    if decision.get("action") == "go":
        return temporal.get("risk") == "clear" and factor == 1 and decision.get("state") == "clear"
    # Steering still needs the original independent sector/ground checks.
    return steering and factor == 0 and temporal.get("state") == "obstacle"


def reply_valid(config, decision):
    if not active(config):
        return _legacy_reply_valid(decision)
    try:
        expected = validate_behavior(config["behavior"])
        received = validate_behavior(decision.get("behavior"))
    except (ValueError, KeyError):
        return False
    if received != expected or decision.get("effective_policy_sha256") != policy_digest(
        expected, config.get("perception")
    ):
        return False
    if decision.get("action") == "stop":
        return True
    temporal = decision.get("temporal")
    if not _temporal_evidence_valid(temporal, decision):
        return False
    return _temporal_action_valid(config, expected, decision, temporal)
