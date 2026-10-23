"""Immutable experimental navigation policies; shared host/Pi wire definitions."""

from __future__ import annotations

import hashlib
import json

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
    if (
        not isinstance(value, dict)
        or set(value) != set(DEFAULT_BEHAVIOR)
        or type(value.get("version")) is not int
        or value["version"] != 1
        or type(value.get("profile_revision")) is not int
        or value["profile_revision"] != 1
        or not isinstance(value.get("profile_id"), str)
        or value["profile_id"] not in {"legacy", *_OVERRIDES}
    ):
        raise ValueError("navigation_behavior_invalid")
    return dict(value)


def parameters(value):
    behavior = validate_behavior(value)
    profile = behavior["profile_id"]
    return {} if profile == "legacy" else {**_BASE, **_OVERRIDES[profile]}


def policy_digest(value):
    behavior = validate_behavior(value)
    payload = {"behavior": behavior, "parameters": parameters(behavior)}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def catalog(value=None):
    active = validate_behavior(DEFAULT_BEHAVIOR if value is None else value)
    return {
        "version": 1,
        "supported": True,
        "active": active,
        "effective_policy_sha256": policy_digest(active),
        "profiles": [
            {
                "id": name,
                "profile_revision": 1,
                "status": "legacy" if name == "legacy" else "experimental",
                "parameters": parameters({**DEFAULT_BEHAVIOR, "profile_id": name}),
            }
            for name in ("legacy", *_OVERRIDES)
        ],
    }
