"""Pi-owned motion-kind contract for axis-relative image avoidance."""

import math

FIELDS = {"version", "motion_mode", "center_deadband", "rotation_bounds"}
MODES = {"rotate_then_drive", "steer", "auto"}


def selection(config):
    """Extract optional guidance from the Pi-owned collision configuration."""
    from services.collision_geometry import selection as collision

    value = collision(config)
    return value.get("guidance") if isinstance(value, dict) else None


def validate(value, corridor):
    """Validate and normalize the complete guidance configuration."""
    if (
        not isinstance(value, dict)
        or set(value) != FIELDS
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        raise ValueError("navigation_guidance_invalid")
    if not isinstance(value["motion_mode"], str) or value["motion_mode"] not in MODES:
        raise ValueError("navigation_guidance_invalid")
    deadband = value["center_deadband"]
    if type(deadband) not in (int, float) or not math.isfinite(deadband) or not 0 <= deadband <= 0.25:
        raise ValueError("navigation_guidance_invalid")
    bounds = value["rotation_bounds"]
    if bounds is not None:
        if (
            not isinstance(bounds, list)
            or len(bounds) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
        ):
            raise ValueError("navigation_rotation_geometry_invalid")
        a, b, c, d = bounds
        if not (0 <= a < c <= 1 and 0 <= b < d <= 1 and a <= corridor[0] and c >= corridor[2] and b < corridor[3] <= d):
            raise ValueError("navigation_rotation_geometry_incomplete")
    return {
        **value,
        "center_deadband": float(deadband),
        "rotation_bounds": [float(v) for v in bounds] if bounds is not None else None,
    }


def require_ready(config):
    """Require a visible, calibrated rotation envelope for rotation-only drive."""
    value = selection(config)
    if (
        config.get("mode") == "drive"
        and value is not None
        and value["motion_mode"] == "rotate_then_drive"
        and value["rotation_bounds"] is None
    ):
        raise ValueError("navigation_rotation_calibration_missing")
    if value is not None and value["motion_mode"] == "rotate_then_drive" and config.get("mode") == "drive":
        region = config.get("perception", {}).get("input_region")
        if region is not None:
            if (
                not isinstance(region, dict)
                or not isinstance(region.get("bounds"), list)
                or len(region["bounds"]) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in region["bounds"])
            ):
                raise ValueError("navigation_rotation_input_incomplete")
            a, b, c, d = region["bounds"]
            x0, y0, x1, y1 = value["rotation_bounds"]
            if not (a <= x0 and b <= y0 and c >= x1 and d >= y1):
                raise ValueError("navigation_rotation_input_incomplete")


def allows_turn(config):
    """Allow in-place turns only for a configured mode with its own envelope."""
    value = selection(config)
    return value is not None and value["motion_mode"] != "steer" and value["rotation_bounds"] is not None


def evidence_valid(config, decision):
    """Check that the decision uses the configured mode and rotation evidence."""
    value = selection(config)
    if value is None:
        return "guidance" not in decision
    if (
        decision.get("guidance") != {"version": 1, "motion_mode": value["motion_mode"]}
        or type(decision["guidance"].get("version")) is not int
    ):
        return False
    action = decision.get("action", "")
    if action.startswith("steer_") and value["motion_mode"] == "rotate_then_drive":
        return False
    if action.startswith("turn_"):
        from services.collision_geometry import path_valid

        return allows_turn(config) and path_valid(decision, "rotation")
    return True


def require_host(status, version):
    """Reject a requested guidance contract unsupported by the host."""
    from apps.compute.client import ComputeError

    if version is not None and (
        type(version) is not int
        or version != 1
        or not isinstance(status, dict)
        or status.get("axis_guidance_v1") is not True
    ):
        raise ComputeError("navigation_guidance_update_required", 409)
