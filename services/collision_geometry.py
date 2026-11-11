"""Stdlib-only validation of the paired image collision contract; no hardware."""

import hashlib
import json
import math

FIELDS = {"version", "far_width_ratio", "left_shift", "right_shift", "end_fraction", "reference_corridor"}


def selection(config):
    """Extract optional collision geometry without assuming nested policy types."""
    value = config
    for key in ("avoidance", "geometry", "collision"):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def validate(value, corridor):
    """Validate the image envelope and its floor-reference support."""
    if (
        not isinstance(value, dict)
        or not FIELDS <= set(value)
        or set(value) - FIELDS - {"guidance"}
        or type(value.get("version")) is not int
        or value["version"] != 1
    ):
        raise ValueError("navigation_collision_geometry_invalid")
    for key, low, high in (
        ("far_width_ratio", 0, 1),
        ("left_shift", 0, 1),
        ("right_shift", 0, 1),
        ("end_fraction", 0.05, 0.5),
    ):
        v = value[key]
        if (
            type(v) not in (int, float)
            or not math.isfinite(v)
            or not low <= v <= high
            or (key == "far_width_ratio" and v == 0)
        ):
            raise ValueError("navigation_collision_geometry_invalid")
    reference = value["reference_corridor"]
    if (
        not isinstance(reference, list)
        or len(reference) != 4
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in reference)
    ):
        raise ValueError("navigation_collision_geometry_invalid")
    a, b, c, d = reference
    x0, y0, x1, y1 = corridor
    if not (0 <= a <= x0 < x1 <= c <= 1 and 0 <= b <= y0 < y1 <= d <= 1):
        raise ValueError("navigation_collision_reference_incomplete")
    if d - b + 1e-9 < min(0.30, y1) or c - a + 1e-9 < min(0.30, x1):
        raise ValueError("navigation_collision_reference_insufficient")
    if "guidance" in value:
        from services.axis_guidance import validate as validate_guidance

        validate_guidance(value["guidance"], corridor)
    return value


def proof(config):
    """Digest normalized collision geometry and the exact configured corridor."""
    value = selection(config)
    validate(value, config["corridor"])
    normalized = {key: float(value[key]) for key in FIELDS - {"version", "reference_corridor"}}
    normalized.update(version=1, reference_corridor=[float(v) for v in value["reference_corridor"]])
    if "guidance" in value:
        from services.axis_guidance import validate as validate_guidance

        normalized["guidance"] = validate_guidance(value["guidance"], config["corridor"])
    payload = {"collision": normalized, "corridor": [float(v) for v in config["corridor"]]}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {"version": 1, "sha256": hashlib.sha256(encoded.encode()).hexdigest()}


def evidence_valid(config, decision):
    """Independently check geometry identity and required directional evidence."""
    from services.axis_guidance import evidence_valid as guidance_valid

    actual = decision.get("collision_geometry")
    if selection(config) is None:
        return actual is None
    try:
        return (
            isinstance(actual, dict)
            and type(actual.get("version")) is int
            and actual == proof(config)
            and decision.get("geometry") == "image_collision_corridor"
            and path_valid(
                decision,
                "center",
                require_clear=decision.get("action") in {"go", "slow"},
            )
            and path_valid(decision, "guard")
            and guidance_valid(config, decision)
        )
    except (ValueError, KeyError, TypeError):
        return False


def path_valid(decision, name, *, require_clear=True):
    """Require sufficient, fully observed pixels and optionally a clear path."""
    paths = decision.get("paths")
    row = paths.get(name) if isinstance(paths, dict) else None
    return (
        isinstance(row, dict)
        and row.get("geometry") == "image_collision_corridor"
        and row.get("coverage_complete") is True
        and type(row.get("zone_pixels")) is int
        and row["zone_pixels"] >= 64
        and (not require_clear or row.get("state") == "clear")
    )


def require_host(status, version):
    """Reject a requested collision contract unsupported by the host."""
    from apps.compute.client import ComputeError

    if version is not None and (
        type(version) is not int
        or version != 1
        or not isinstance(status, dict)
        or status.get("collision_geometry_v1") is not True
    ):
        raise ComputeError("navigation_collision_update_required", 409)


def preparation_options(config):
    """Request all collision-related capabilities required by this policy."""
    from services.axis_guidance import selection as guidance

    options = {"collision_geometry_version": 1} if selection(config) is not None else {}
    if guidance(config) is not None:
        options["axis_guidance_version"] = 1
    return options
