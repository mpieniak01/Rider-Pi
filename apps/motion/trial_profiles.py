"""Fixed pulse-trial recipes. Importing this catalog never opens hardware."""

import hashlib
import json

VERSION = 1
MAX_RUN_S = 1.5
PROFILES = {
    "A": {"id": "A", "version": 1, "count": 1, "pulse_ms": 500, "gap_ms": 0},
    "B": {"id": "B", "version": 1, "count": 2, "pulse_ms": 250, "gap_ms": 100},
    "C": {"id": "C", "version": 1, "count": 5, "pulse_ms": 100, "gap_ms": 100},
}
RAMP_FIELDS = (
    "linear_rate",
    "linear_deceleration",
    "turn_rate",
    "turn_deceleration",
    "reversal_pause",
    "ramp_mode",
    "speed_limit",
)


def recipe(command):
    profile = command.get("trial_profile_id")
    if not isinstance(profile, str) or profile not in PROFILES:
        raise ValueError("pulse_trial_profile_invalid")
    if type(command.get("trial_version")) is not int or command["trial_version"] != VERSION:
        raise ValueError("pulse_trial_version_invalid")
    if (
        command.get("action") != "arm"
        or command.get("source") != "manual"
        or command.get("execution_context") != "panel"
        or command.get("owner") != "manual"
        or command.get("arming_mode") != "operator"
    ):
        raise ValueError("pulse_trial_panel_only")
    if not isinstance(command.get("panel_id"), str) or not command["panel_id"].strip():
        raise ValueError("invalid_panel_id")
    context = command.get("trial_context", "")
    if not isinstance(context, str) or len(context) > 80:
        raise ValueError("pulse_trial_context_invalid")
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
        "trial_profile_id",
        "trial_version",
        "trial_context",
    }
    if set(command) - allowed:
        raise ValueError("pulse_trial_ambiguous")
    return dict(PROFILES[profile])


def common_settings(controls, context, actuators):
    row = controls["directions"]["forward"]
    value = {
        "direction": "forward",
        "parameters": {key: row[key] for key in ("speed", "minimum", "maximum", "step")},
        "ramps": {key: controls["values"][key] for key in RAMP_FIELDS},
        "context": context,
        "posture": actuators,
    }
    digest = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return value, digest
