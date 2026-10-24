"""Immutable experimental navigation policies; shared host/Pi wire definitions."""

from __future__ import annotations

import hashlib
import json

from services.policy_parameters import NEW_DEFAULTS, SCHEMA, validate_effective, validate_overrides

DEFAULT_BEHAVIOR = {"version": 1, "profile_id": "legacy", "profile_revision": 1}
_BASE = {
    "pixel_confidence": 0.75,
    "min_region_fraction": 0.002,
    "thin_span_fraction": 0.15,
    "near_zone_fraction": 0.35,
    "min_floor_fraction": 0.95,
    "min_near_floor_fraction": 0.97,
    "max_uncertain_fraction": 0.03,
    "enter_frames": 2,
    "enter_ms": 60,
    "release_frames": 3,
    "release_ms": 100,
    "history_ms": 500,
    "max_gap_ms": 300,
    "max_uncertain_ms": 160,
    "min_tracking_ratio": 0.5,
    "slow_speed_factor": 0.5,
}
_OVERRIDES = {
    "cautious": {
        "pixel_confidence": 0.8,
        "min_region_fraction": 0.001,
        "min_floor_fraction": 0.98,
        "min_near_floor_fraction": 0.99,
        "max_uncertain_fraction": 0.01,
        "enter_frames": 1,
        "enter_ms": 0,
        "release_ms": 60,
        "max_uncertain_ms": 100,
        "slow_speed_factor": 0.35,
    },
    "balanced": {},
    "fluid": {
        "pixel_confidence": 0.7,
        "min_region_fraction": 0.003,
        "min_floor_fraction": 0.92,
        "min_near_floor_fraction": 0.95,
        "max_uncertain_fraction": 0.06,
        "enter_frames": 3,
        "enter_ms": 100,
        "release_ms": 100,
        "max_uncertain_ms": 200,
        "slow_speed_factor": 0.6,
    },
}


def validate_behavior(value):
    required = set(DEFAULT_BEHAVIOR)
    if (
        not isinstance(value, dict)
        or not required <= set(value)
        or set(value) - required - {"overrides"}
        or type(value.get("version")) is not int
        or value["version"] != 1
        or type(value.get("profile_revision")) is not int
        or value["profile_revision"] not in (1, 2)
        or not isinstance(value.get("profile_id"), str)
        or value["profile_id"] not in {"legacy", *_OVERRIDES}
        or value["profile_id"] == "legacy"
        and value["profile_revision"] != 1
    ):
        raise ValueError("navigation_behavior_invalid")
    corrections = validate_overrides(value.get("overrides", {}))
    if corrections and (value["profile_id"] == "legacy" or value["profile_revision"] != 2):
        raise ValueError("navigation_behavior_overrides_invalid")
    result = dict(value)
    if corrections:
        result["overrides"] = corrections
        validate_effective({**_preset(result), **corrections})
    else:
        result.pop("overrides", None)
    return result


def _preset(behavior):
    profile = behavior["profile_id"]
    if profile == "legacy":
        return {}
    values = {**_BASE, **_OVERRIDES[profile]}
    if behavior["profile_revision"] == 2:
        values.update(NEW_DEFAULTS)
        if profile == "fluid":
            values["obstacle_support_frames"] = 2
    return values


def parameters(value, perception=None):
    behavior = validate_behavior(value)
    profile = behavior["profile_id"]
    if profile == "legacy":
        return {}
    result = _preset(behavior)
    if perception is not None:
        from services.perception_tuning import (
            SEMANTIC_MODELS,
            active_model_id,
            has_semantic_tuning,
            semantic_parameters,
        )

        if active_model_id(perception) in SEMANTIC_MODELS and has_semantic_tuning(perception):
            result.update(semantic_parameters(perception, behavior))
    result.update(behavior.get("overrides", {}))
    return validate_effective(result)


def policy_digest(value, perception=None):
    behavior = validate_behavior(value)
    payload = {"behavior": behavior, "parameters": parameters(behavior, perception)}
    if behavior["profile_id"] == "legacy" and perception is not None:
        from services.perception_tuning import has_semantic_tuning, semantic_parameters

        if has_semantic_tuning(perception):
            payload["semantic"] = semantic_parameters(perception, behavior)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def catalog(value=None, perception=None):
    active = validate_behavior(DEFAULT_BEHAVIOR if value is None else value)
    return {
        "version": 1,
        "supported": True,
        "active": active,
        "parameter_editing_version": 1,
        "parameter_schema": {key: dict(spec) for key, spec in SCHEMA.items()},
        "active_parameters": parameters(active, perception),
        "active_base_parameters": parameters({k: v for k, v in active.items() if k != "overrides"}, perception),
        "custom": bool(active.get("overrides")),
        "effective_policy_sha256": policy_digest(active, perception),
        "profiles": [
            {
                "id": name,
                "profile_revision": 1 if name == "legacy" else 2,
                "status": "legacy" if name == "legacy" else "experimental",
                "parameters": parameters(
                    {**DEFAULT_BEHAVIOR, "profile_id": name, "profile_revision": 1 if name == "legacy" else 2},
                    perception,
                ),
            }
            for name in ("legacy", *_OVERRIDES)
        ],
    }
