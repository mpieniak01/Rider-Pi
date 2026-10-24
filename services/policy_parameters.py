"""Bounded operator corrections for versioned vision policy presets."""

import math

NEW_DEFAULTS = {
    "obstacle_support_frames": 1,
    "obstacle_window_frames": 3,
    "obstacle_match_overlap": 0.1,
    "obstacle_match_tolerance_px": 1,
    "obstacle_min_previous_coverage": 0.9,
    "object_tracking_enabled": False,
    "object_min_area_px": 80,
    "object_match_iou": 0.1,
    "object_appearance_min": 0.2,
    "object_area_ratio_min": 0.5,
    "object_area_ratio_max": 2.0,
    "object_max_gap_frames": 2,
    "object_trend_frames": 3,
    "object_growth_min": 1.1,
    "object_lower_min_px": 2,
}


def _field(kind, low, high, step, group):
    return {"kind": kind, "min": low, "max": high, "step": step, "group": group}


SCHEMA = {
    "pixel_confidence": _field("float", 0.05, 1.0, 0.01, "evidence"),
    "min_region_fraction": _field("float", 0.0, 0.02, 0.001, "evidence"),
    "thin_span_fraction": _field("float", 0.01, 1.0, 0.01, "evidence"),
    "near_zone_fraction": _field("float", 0.05, 1.0, 0.05, "evidence"),
    "min_floor_fraction": _field("float", 0.5, 1.0, 0.01, "evidence"),
    "min_near_floor_fraction": _field("float", 0.5, 1.0, 0.01, "evidence"),
    "max_uncertain_fraction": _field("float", 0.0, 0.5, 0.01, "evidence"),
    "enter_frames": _field("int", 1, 8, 1, "temporal"),
    "enter_ms": _field("int", 0, 1000, 10, "temporal"),
    "release_frames": _field("int", 1, 8, 1, "temporal"),
    "release_ms": _field("int", 0, 1000, 10, "temporal"),
    "history_ms": _field("int", 100, 2000, 50, "temporal"),
    "max_gap_ms": _field("int", 50, 1000, 10, "temporal"),
    "max_uncertain_ms": _field("int", 0, 1000, 10, "temporal"),
    "min_tracking_ratio": _field("float", 0.1, 1.0, 0.05, "temporal"),
    "slow_speed_factor": _field("float", 0.1, 1.0, 0.05, "temporal"),
    "obstacle_support_frames": _field("int", 1, 5, 1, "persistence"),
    "obstacle_window_frames": _field("int", 2, 5, 1, "persistence"),
    "obstacle_match_overlap": _field("float", 0.01, 1.0, 0.01, "persistence"),
    "obstacle_match_tolerance_px": _field("int", 0, 3, 1, "persistence"),
    "obstacle_min_previous_coverage": _field("float", 0.5, 1.0, 0.05, "persistence"),
    "object_tracking_enabled": _field("bool", 0, 1, 1, "objects"),
    "object_min_area_px": _field("int", 8, 4096, 8, "objects"),
    "object_match_iou": _field("float", 0.01, 0.9, 0.01, "objects"),
    "object_appearance_min": _field("float", 0.0, 1.0, 0.05, "objects"),
    "object_area_ratio_min": _field("float", 0.1, 1.0, 0.05, "objects"),
    "object_area_ratio_max": _field("float", 1.0, 5.0, 0.1, "objects"),
    "object_max_gap_frames": _field("int", 0, 3, 1, "objects"),
    "object_trend_frames": _field("int", 2, 5, 1, "objects"),
    "object_growth_min": _field("float", 1.0, 3.0, 0.05, "objects"),
    "object_lower_min_px": _field("int", 0, 40, 1, "objects"),
}


def validate_overrides(value):
    if not isinstance(value, dict) or set(value) - set(SCHEMA):
        raise ValueError("navigation_behavior_overrides_invalid")
    for name, number in value.items():
        spec = SCHEMA[name]
        if spec["kind"] == "bool":
            valid = type(number) is bool
        else:
            valid = (
                type(number) in (int, float)
                and spec["min"] <= number <= spec["max"]
                and math.isfinite(number)
                and (spec["kind"] != "int" or type(number) is int)
            )
        if not valid:
            raise ValueError("navigation_behavior_overrides_invalid")
    return dict(value)


def validate_effective(values):
    for name in ("enter_ms", "release_ms", "max_gap_ms", "max_uncertain_ms"):
        if values[name] > values["history_ms"]:
            raise ValueError("navigation_behavior_overrides_invalid")
    if values.get("obstacle_support_frames", 1) > values.get("obstacle_window_frames", 3):
        raise ValueError("navigation_behavior_overrides_invalid")
    if values.get("object_area_ratio_min", 0.5) > values.get("object_area_ratio_max", 2.0):
        raise ValueError("navigation_behavior_overrides_invalid")
    return values
