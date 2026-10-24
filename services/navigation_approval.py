"""Narrow approval changes leave inference parameters and movement policy intact."""

from copy import deepcopy


def approval_only(old, new):
    if (
        new.get("revision") != old.get("revision", -1) + 1
        or new.get("verified") is not True
        or not new.get("calibration_id")
        or new.get("calibration_id") == old.get("calibration_id")
        or not new.get("model_sha256")
    ):
        return False

    def runtime_policy(config):
        policy = deepcopy(config)
        for key in ("revision", "verified", "calibration_id", "model_sha256"):
            policy.pop(key, None)
        policy.get("avoidance", {}).pop("sweep_verified", None)
        return policy

    return runtime_policy(old) == runtime_policy(new)


def passive_navigation_matches(revision):
    """S14 may survive a mission only as a fresh, authority-free observer."""
    import math
    import time

    from services.navigation_trial import navigation_status
    from services.safety_contract import read_status

    status = navigation_status()
    sampled = status.get("sampled_monotonic")
    if not (
        status.get("running") is True
        and status.get("mode") == "observe"
        and status.get("config_revision") == revision
        and type(sampled) in (int, float)
        and math.isfinite(sampled)
        and 0 <= time.monotonic() - sampled <= 1
    ):
        return False
    safety = read_status()
    return (
        safety.get("ready") is True
        and safety.get("stale") is False
        and safety.get("state") in {"ARMED", "DISARMED", "ESTOP"}
        and not (safety.get("can_move") is True and safety.get("owner") == "navigation")
        and (safety.get("journey") or {}).get("active") is not True
    )
