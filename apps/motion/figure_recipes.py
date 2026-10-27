"""Own bounded motion recipes; native ACTION/PERFORM generators are never used."""

import copy
import hashlib
import json
import math

VERSION = 1
HEARTBEAT_S = 0.5
MAX_ROLL = 5.0
BASE_HEIGHT = 90
NAMES = {
    "sway": 1,
    "vertical": 2,
    "forward_backward": 3,
    "snake": 4,
    "lift_rotate": 5,
    "circular_sway": 6,
}


def step(ms, **axes):
    return {"ms": ms, **axes}


def recipes():
    return {
        "sway": [step(500, roll=0)] + [step(700, roll=x) for x in (3, -3, 3, -3, 0)],
        "vertical": [step(500, height=90)] + [step(800, height=x) for x in (95, 85, 95, 90)],
        "forward_backward": [
            step(300),
            step(700, linear_factor=0.3),
            step(300),
            step(700, linear_factor=-0.3),
            step(300),
        ],
        "snake": [step(300)]
        + [
            item
            for turn in (-0.3, 0.3, -0.3, 0.3)
            for item in (step(700, linear_factor=0.3, turn_factor=turn), step(250))
        ],
        "lift_rotate": [
            step(500, height=90),
            step(900, height=95, turn_factor=-0.3),
            step(900, height=85, turn_factor=-0.3),
            step(900, height=90, turn_factor=0.3),
            step(300),
        ],
        "circular_sway": [step(500, height=90, roll=0)]
        + [
            step(500, height=round(90 + 5 * math.sin(i * math.pi / 4)), roll=round(3 * math.cos(i * math.pi / 4), 2))
            for i in range(8)
        ]
        + [step(500, height=90, roll=0)],
    }


def validate_request(command):
    allowed = {
        "action",
        "request_id",
        "source",
        "execution_context",
        "generation",
        "seq",
        "ts",
        "ttl_ms",
        "settings_revision",
        "operator_consent",
        "operator_plan",
        "owner",
        "arming_mode",
        "panel_id",
        "figure_id",
        "figure_version",
        "figure_run_id",
    }
    if set(command) - allowed:
        raise ValueError("figure_ambiguous")
    if command.get("figure_id") not in NAMES:
        raise ValueError("figure_unknown")
    if type(command.get("figure_version")) is not int or command["figure_version"] != VERSION:
        raise ValueError("figure_version_invalid")
    if (
        any(
            command.get(k) != v
            for k, v in {
                "action": "arm",
                "source": "manual",
                "execution_context": "panel",
                "owner": "manual",
                "arming_mode": "operator",
                "operator_consent": True,
            }.items()
        )
        or command.get("operator_consent") is not True
    ):
        raise ValueError("figure_panel_consent_required")
    for field in ("request_id", "panel_id", "operator_plan"):
        if not isinstance(command.get(field), str) or not command[field].strip():
            raise ValueError("figure_identity_required")
    if type(command.get("settings_revision")) is not int:
        raise ValueError("manual_settings_stale")
    return command["figure_id"]


def compile_recipe(identifier, controls):
    rows = copy.deepcopy(recipes()[identifier])
    for row in rows:
        for field, axis, positive, negative in (
            ("linear_factor", "vx", "forward", "backward"),
            ("turn_factor", "yaw", "right", "left"),
        ):
            factor = row.pop(field, 0.0)
            preset = controls["directions"][positive if factor >= 0 else negative]
            magnitude = min(0.25, controls["values"]["speed_limit"], preset["speed"] * abs(factor))
            if factor and not preset["minimum"] <= magnitude <= preset["maximum"]:
                raise ValueError("figure_direction_range")
            row[axis] = math.copysign(magnitude, factor)
    return rows


def fingerprint(command):
    return hashlib.sha256(json.dumps(command, sort_keys=True, allow_nan=False).encode()).hexdigest()


def catalog(axes=None):
    axes = axes or {}
    result = []
    for identifier, rows in recipes().items():
        required = sorted({key for row in rows for key in ("height", "roll") if key in row})
        available = all(axes.get(key) is True for key in required)
        result.append(
            {
                "id": identifier,
                "version": VERSION,
                "reference_action": NAMES[identifier],
                "implementation": "own_sequence",
                "qualification": "manual_trial",
                "physical_completion": "unverified",
                "available": available,
                "reason": "" if available else "figure_posture_unsupported",
                "duration_ms": sum(row["ms"] for row in rows),
                "steps": len(rows),
                "required_axes": required,
                "initial_height": 90 if "height" in required else None,
                "initial_roll": 0 if "roll" in required else None,
                "height_range": [85, 95] if "height" in required else None,
                "roll_range": [-3, 3] if "roll" in required else None,
                "maximum_speed": 0.25,
                "intensity_factor": 0.3,
            }
        )
    return {
        "version": VERSION,
        "implementation": "own_sequence",
        "figures": result,
        "heartbeat_ms": 200,
        "heartbeat_timeout_ms": round(HEARTBEAT_S * 1000),
    }
