"""Device-authoritative motion settings. File transactions never actuate hardware."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from apps.motion.dynamics import RampLimits, finite
from common.actuator_parameters import posture_parameters

FIELDS = {"linear_speed", "turn_speed", "pulse_duration", "speed_limit", "linear_rate", "turn_rate"}
SMOOTHING = {"linear_deceleration", "turn_deceleration", "reversal_pause", "ramp_mode"}
MAX_PANEL_DURATION_S = 1.0

DIRECTIONS = ("forward", "backward", "left", "right")
_LOCK = threading.RLock()
_LOCAL = threading.local()


def path():
    override = os.getenv("RIDER_MANUAL_SETTINGS_PATH")
    target = Path(override) if override else Path.home() / ".local/state/rider/motion/settings.json"
    if not target.is_absolute():
        raise ValueError("manual_settings_absolute_path_required")
    if os.getenv("RIDER_TEST_ISOLATED") == "1" and not override:
        raise ValueError("manual_settings_test_path_required")
    return target


@contextmanager
def locked(*, blocking=True):
    """Executor never waits on API persistence; STOP dispatch stays responsive."""
    if not _LOCK.acquire(blocking=blocking):
        raise BlockingIOError("manual_settings_busy")
    try:
        if getattr(_LOCAL, "depth", 0):
            _LOCAL.depth += 1
            try:
                yield
            finally:
                _LOCAL.depth -= 1
            return
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(str(target) + ".lock", "a") as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            _LOCAL.depth = 1
            try:
                yield
            finally:
                _LOCAL.depth = 0
    finally:
        _LOCK.release()


def limits():
    return {
        "linear_speed": 1.0,
        "turn_speed": 1.0,
        "pulse_duration": MAX_PANEL_DURATION_S,
        "speed_limit": 1.0,
        "linear_rate": 100.0,
        "turn_rate": 100.0,
        "linear_deceleration": 100.0,
        "turn_deceleration": 100.0,
        "reversal_pause": 0.25,
        "ramp_mode": 2,
    }


# Public descriptions and timing are owned by the device, never by clients.
HOLD_RENEWAL_S = 0.15
HOLD_TIMEOUT_S = 0.5


def parameter_schema():
    def field(unit, display_unit, factor, minimum, maximum, precision, meaning):
        return {
            "type": "number",
            "unit": unit,
            "display_unit": display_unit,
            "display_factor": factor,
            "minimum": minimum,
            "maximum": maximum,
            "display_precision": precision,
            "meaning": meaning,
        }

    def magnitude(meaning):
        return field("normalized_command", "%", 100, 0, 1, 1, meaning)

    cap = limits()
    return {
        "version": 1,
        "actuator_fields": posture_parameters(),
        "ramp_modes": [
            {"value": 0, "id": "linear", "label_pl": "Liniowy", "label_en": "Linear"},
            {"value": 1, "id": "smooth_s", "label_pl": "Łagodny S", "label_en": "Smooth S"},
            {"value": 2, "id": "logarithmic", "label_pl": "Logarytmiczny", "label_en": "Logarithmic"},
        ],
        "direction_fields": {
            "speed": magnitude("command_magnitude_not_physical_speed"),
            "minimum": magnitude("operator_defined_minimum_nonzero_command"),
            "maximum": magnitude("profile_command_ceiling"),
            "step": field("normalized_command", "%", 100, 0, 1, 3, "manual_adjustment_step")
            | {"exclusive_minimum": True},
            "duration": field("s", "ms", 1000, 0.01, MAX_PANEL_DURATION_S, 0, "whole_click_pulse"),
        },
        "value_fields": {
            key: field("normalized_command/s", "%/s", 100, 0.001, cap[key], 1, key)
            for key in ("linear_rate", "turn_rate", "linear_deceleration", "turn_deceleration")
        }
        | {"reversal_pause": field("s", "ms", 1000, 0, cap["reversal_pause"], 0, "pause_before_reversal")},
        "constraints": [
            {"id": "direction_range", "rule": "minimum <= maximum"},
            {"id": "direction_speed", "rule": "speed == 0 or minimum <= speed <= maximum"},
            {"id": "direction_step", "rule": "step > 0; zero-width range permits a disabled slider"},
            {"id": "pulse_minimum", "rule": "minimum <= duration / (1/acceleration + 1/deceleration)"},
        ],
    }


def control_modes():
    return {
        "version": 1,
        "supported": ["pulse", "hold", "release"],
        "default": "pulse",
        "directions": list(DIRECTIONS),
        "hold_renewal_ms": round(HOLD_RENEWAL_S * 1000),
        "hold_timeout_ms": round(HOLD_TIMEOUT_S * 1000),
        "click_threshold_ms": 180,
        "request_ttl_ms": 500,
        "replacement": "latest_valid_sequence_wins",
        "release": "decelerate_keep_armed",
        "release_timeout_ms": round(HOLD_TIMEOUT_S * 1000),
        "stop": "immediate_disarm",
        "hold_permission": "operator_manual_panel",
        "settings_change": "idle_only",
        "command": {
            "endpoint": "/api/control",
            "action": "move",
            "fields": ["direction", "mode", "device_settings", "settings_revision"],
        },
    }


def defaults():
    cap = limits()
    baseline = RampLimits.from_env()
    return {
        "linear_speed": min(0.2, cap["speed_limit"]),
        "turn_speed": min(0.35, cap["speed_limit"]),
        "pulse_duration": 0.25,
        "speed_limit": cap["speed_limit"],
        "linear_rate": baseline.linear_rate,
        "turn_rate": baseline.turn_rate,
        "linear_deceleration": baseline.linear_rate,
        "turn_deceleration": baseline.turn_rate,
        "reversal_pause": 0.0,
        "ramp_mode": 0,
    }


def validate(values):
    if not isinstance(values, dict) or set(values) != FIELDS | SMOOTHING:
        raise ValueError("manual_settings_fields")
    cap = limits()
    for key, value in values.items():
        if key == "ramp_mode":
            if type(value) is not int or value not in (0, 1, 2):
                raise ValueError("manual_settings_ramp_mode")
            continue
        minimum = (
            0 if key in {"linear_speed", "turn_speed", "reversal_pause"} else 0.01 if key == "pulse_duration" else 0.001
        )
        if not finite(value) or not minimum <= value <= cap[key]:
            raise ValueError("manual_settings_" + key)
    if max(values["linear_speed"], values["turn_speed"]) > values["speed_limit"]:
        raise ValueError("manual_settings_speed_limit")
    return dict(values)


def direction_defaults(values):
    return {
        name: {
            "minimum": 0.0,
            "maximum": values["speed_limit"],
            "step": 0.01,
            "speed": values["linear_speed" if name in DIRECTIONS[:2] else "turn_speed"],
            "duration": values["pulse_duration"],
        }
        for name in DIRECTIONS
    }


def validate_directions(directions, values):
    if not isinstance(directions, dict) or set(directions) != set(DIRECTIONS):
        raise ValueError("manual_settings_directions")
    result = {}
    for name, row in directions.items():
        if not isinstance(row, dict) or set(row) != {"minimum", "maximum", "step", "speed", "duration"}:
            raise ValueError("manual_settings_direction_fields")
        if not all(finite(value) for value in row.values()):
            raise ValueError("manual_settings_direction_number")
        if not 0 <= row["minimum"] <= row["maximum"] <= values["speed_limit"]:
            raise ValueError("manual_settings_direction_range")
        if not 0 < row["step"] <= 1 or not 0.01 <= row["duration"] <= MAX_PANEL_DURATION_S:
            raise ValueError("manual_settings_direction_step_or_duration")
        if row["speed"] != 0 and not row["minimum"] <= row["speed"] <= row["maximum"] or row["speed"] < 0:
            raise ValueError("manual_settings_direction_speed")
        rate = values["linear_rate" if name in DIRECTIONS[:2] else "turn_rate"]
        deceleration = values["linear_deceleration" if name in DIRECTIONS[:2] else "turn_deceleration"]
        peak = row["duration"] / (1 / rate + 1 / deceleration)
        if row["minimum"] > peak:
            raise ValueError("manual_settings_pulse_too_short_for_minimum")
        result[name] = dict(row)
    return result


def _decode(target):
    with target.open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("manual_settings_oversized")

    def pairs(items):
        row = {}
        for key, value in items:
            if key in row:
                raise ValueError("manual_settings_duplicate_key")
            row[key] = value
        return row

    return json.loads(raw, object_pairs_hook=pairs)


def _canonical(row):
    if not isinstance(row, dict) or type(row.get("revision")) is not int or row["revision"] < 0:
        raise ValueError("manual_settings_revision")
    if set(row) - {"schema_version", "revision", "values", "directions", "profiles", "active_profile"}:
        raise ValueError("manual_settings_fields")
    if type(row.get("schema_version", 1)) is not int or row.get("schema_version", 1) not in (1, 2):
        raise ValueError("manual_settings_schema")
    if row.get("schema_version") == 2 and "directions" not in row:
        raise ValueError("manual_settings_directions_required")
    values = row.get("values")
    if row.get("schema_version", 1) == 1:
        if not isinstance(values, dict) or set(values) != FIELDS:
            raise ValueError("manual_settings_fields")
        # Preserve effective old commands, previously clamped by MotionController.
        values = dict(values)
        for key in ("linear_speed", "turn_speed"):
            if not finite(values[key]) or not 0 <= values[key] <= 1:
                raise ValueError("manual_settings_" + key)
            values[key] = min(values[key], values["speed_limit"])
        values.update(
            linear_deceleration=values["linear_rate"], turn_deceleration=values["turn_rate"], reversal_pause=0.0
        )
    if not isinstance(values, dict):
        raise ValueError("manual_settings_fields")
    values = dict(values, ramp_mode=values.get("ramp_mode", 0))
    values = validate(values)
    directions = validate_directions(row.get("directions", direction_defaults(values)), values)
    # Explicit aliases for older readers, derived from the authoritative rows.
    values.update(
        linear_speed=directions["forward"]["speed"],
        turn_speed=directions["right"]["speed"],
        pulse_duration=max(item["duration"] for item in directions.values()),
    )
    profiles = row.get("profiles", {})
    active = row.get("active_profile")
    if not isinstance(profiles, dict) or len(profiles) > 16:
        raise ValueError("manual_profiles_limit")
    saved = {}
    for key, profile in profiles.items():
        if not isinstance(key, str) or len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("manual_profile_id")
        if not isinstance(profile, dict) or set(profile) != {"name", "values", "directions"}:
            raise ValueError("manual_profile_fields")
        name = profile_name(profile["name"])
        canonical = _canonical(
            {"schema_version": 2, "revision": 0, "values": profile["values"], "directions": profile["directions"]}
        )
        saved[key] = {"name": name, "values": canonical["values"], "directions": canonical["directions"]}
    if active is not None and (not isinstance(active, str) or active not in saved):
        raise ValueError("manual_profile_active")
    return {
        "schema_version": 2,
        "revision": row["revision"],
        "values": values,
        "directions": directions,
        "profiles": saved,
        "active_profile": active,
    }


def profile_name(name):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or any(ord(c) < 32 for c in name):
        raise ValueError("manual_profile_name")
    return name.strip()


def profile_modified(row):
    active = row.get("profiles", {}).get(row.get("active_profile"))
    return bool(active and any(row[key] != active[key] for key in ("values", "directions")))


def _atomic(row):
    encoded = json.dumps(row, allow_nan=False).encode("utf-8")
    if len(encoded) > 65536:
        raise ValueError("manual_settings_oversized")
    target = path()
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".motion-settings-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(encoded.decode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, target)
        tmp = None
    finally:
        if tmp is not None:
            os.unlink(tmp)


def read(*, blocking=True):
    with locked(blocking=blocking):
        target = path()
        if target.exists():
            original = _decode(target)
            row = _canonical(original)
            if row != original:
                row["revision"] += 1
                _atomic(row)
            return row
        legacy = Path(__file__).resolve().parents[2] / "config/local/manual-controls.json"
        # Explicit paths are independent stores, including isolated WSL tests.
        if not os.getenv("RIDER_MANUAL_SETTINGS_PATH") and legacy.exists():
            row = _canonical(_decode(legacy))
            row["revision"] += 1  # Old client values must be refreshed after migration.
        else:
            values = defaults()
            revision = 0
            # A saved legacy profile is a migration input only when no manual
            # settings exist. It can never replace an existing authoritative file.
            if not os.getenv("RIDER_MANUAL_SETTINGS_PATH"):
                from apps.motion import calibration_profiles

                active = calibration_profiles.read_active()
                if active is not None:
                    profile = calibration_profiles.read_profile(active["profile_digest"])
                    legacy_values = {key: values[key] for key in FIELDS}
                    legacy_values.update(profile["motion"], **(profile.get("interaction") or {}))
                    migrated = _canonical({"revision": 0, "values": legacy_values})
                    values = migrated["values"]
                    revision = 1
            row = _canonical(
                {"schema_version": 2, "revision": revision, "values": values, "directions": direction_defaults(values)}
            )
        _atomic(row)
        return row


def snapshot():
    row = read()
    return dict(
        row,
        contract_id="rider.manual_settings",
        contract_version=2,
        observed_at=time.time(),
        limits=limits(),
        actuation=False,
        units="normalized_command",
        legacy_units_scope="command_magnitude_only; use parameter_schema for individual fields",
        parameter_schema=parameter_schema(),
        control_modes=control_modes(),
        authority="device",
        profile_modified=profile_modified(row),
        legacy_aliases={
            "linear_speed": "directions.forward.speed",
            "turn_speed": "directions.right.speed",
            "pulse_duration": "maximum_direction_duration",
        },
    )


def update(patch, revision, *, directions=None, validate_state=None):
    with locked():
        current = read()
        if type(revision) is not int or revision != current["revision"]:
            raise ValueError("manual_settings_conflict")
        if validate_state is not None:
            validate_state()
        row = _updated(current, patch, directions)
        if row == current:
            return current
        row["revision"] += 1
        _atomic(row)
        return row


def pulse(row, direction):
    if direction not in DIRECTIONS:
        raise ValueError("manual_direction")
    item = row["directions"][direction]
    speed = item["speed"]
    vx, yaw = {
        "forward": (speed, 0),
        "backward": (-speed, 0),
        "left": (0, -speed),
        "right": (0, speed),
    }[direction]
    return {"vx": vx, "yaw": yaw, "duration": item["duration"]}


def validate_command(row, values, *, mode="pulse"):
    for axis, positive, negative in (("vx", "forward", "backward"), ("yaw", "right", "left")):
        value = values[axis]
        if value == 0:
            continue
        bounds = row["directions"][positive if value > 0 else negative]
        if not bounds["minimum"] <= abs(value) <= bounds["maximum"]:
            raise ValueError("manual_settings_direction_range")
        if mode == "pulse" and values["duration"] > bounds["duration"]:
            raise ValueError("manual_settings_duration")


def _updated(current, patch, directions):
    if not isinstance(patch, dict) or set(patch) - FIELDS - SMOOTHING or not patch and not directions:
        raise ValueError("manual_settings_fields")
    values = validate(dict(current["values"], **patch))
    rows = {name: dict(row) for name, row in current["directions"].items()}
    # Compatibility edits intentionally update both directions of that axis.
    for name, row in rows.items():
        key = "linear_speed" if name in DIRECTIONS[:2] else "turn_speed"
        if key in patch:
            row["speed"] = values[key]
        if "pulse_duration" in patch:
            row["duration"] = values["pulse_duration"]
    if directions is not None:
        if not isinstance(directions, dict) or set(directions) - set(DIRECTIONS):
            raise ValueError("manual_settings_directions")
        for name, edits in directions.items():
            if not isinstance(edits, dict):
                raise ValueError("manual_settings_direction_fields")
            rows[name].update(edits)
    if any(not all(finite(value) for value in row.values()) for row in rows.values()):
        raise ValueError("manual_settings_direction_number")
    # The global command limit is a derived compatibility alias, not a second
    # hidden cap below the per-direction calibration maxima.
    if "speed_limit" not in patch:
        values["speed_limit"] = max(row["maximum"] for row in rows.values())
    values.update(
        linear_speed=rows["forward"]["speed"],
        turn_speed=rows["right"]["speed"],
        pulse_duration=max(row["duration"] for row in rows.values()),
    )
    values = validate(values)
    rows = validate_directions(rows, values)
    row = _canonical(dict(current, values=values, directions=rows))
    return row


def manage_profile(operation, revision, *, patch=None, directions=None, validate_state=None):
    """One atomic device transaction for preset selection and its settings."""
    with locked():
        current = read()
        if type(revision) is not int or revision != current["revision"]:
            raise ValueError("manual_settings_conflict")
        if validate_state is not None:
            validate_state()
        if not isinstance(operation, dict) or set(operation) - {"action", "id", "name"}:
            raise ValueError("manual_profile_operation")
        action, key = operation.get("action"), operation.get("id")
        if action not in {"create", "save", "apply", "rename", "delete"}:
            raise ValueError("manual_profile_operation")
        if action != "create" and (not isinstance(key, str) or key not in current["profiles"]):
            raise ValueError("manual_profile_not_found")
        patch = {} if patch is None else patch
        if not isinstance(patch, dict):
            raise ValueError("manual_settings_fields")
        if action not in {"create", "save"} and (patch or directions):
            raise ValueError("manual_profile_unsaved")
        row = _updated(current, patch, directions) if patch or directions else _canonical(current)
        if action == "create":
            if len(row["profiles"]) >= 16:
                raise ValueError("manual_profiles_limit")
            key = uuid.uuid4().hex
        if action in {"create", "save"}:
            name = profile_name(operation.get("name", row["profiles"].get(key, {}).get("name")))
            row["profiles"][key] = {
                "name": name,
                "values": dict(row["values"]),
                "directions": {k: dict(v) for k, v in row["directions"].items()},
            }
            row["active_profile"] = key
        elif action == "apply":
            saved = row["profiles"][key]
            row["values"], row["directions"] = (
                dict(saved["values"]),
                {k: dict(v) for k, v in saved["directions"].items()},
            )
            row["active_profile"] = key
        elif action == "rename":
            row["profiles"][key]["name"] = profile_name(operation.get("name"))
        else:
            del row["profiles"][key]
            if row["active_profile"] == key:
                row["active_profile"] = None
        row = _canonical(row)
        if row != current:
            row["revision"] += 1
            _atomic(row)
        return row
