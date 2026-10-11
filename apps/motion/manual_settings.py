"""One small, versioned configuration for every manual panel; never actuates."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from pathlib import Path

from apps.motion.dynamics import RampLimits, finite

FIELDS = {"linear_speed", "turn_speed", "pulse_duration", "speed_limit", "linear_rate", "turn_rate"}


def path():
    return Path(
        os.getenv(
            "RIDER_MANUAL_SETTINGS_PATH", str(Path(__file__).resolve().parents[2] / "config/local/manual-controls.json")
        )
    )


def limits():
    row = RampLimits.from_env()
    return {
        "linear_speed": 1,
        "turn_speed": 1,
        "pulse_duration": 0.25,
        "speed_limit": row.speed_limit,
        "linear_rate": row.linear_rate,
        "turn_rate": row.turn_rate,
    }


def defaults():
    cap = limits()
    return {
        "linear_speed": 0.2,
        "turn_speed": 0.35,
        "pulse_duration": 0.25,
        "speed_limit": cap["speed_limit"],
        "linear_rate": cap["linear_rate"],
        "turn_rate": cap["turn_rate"],
    }


def validate(values):
    cap = limits()
    if not isinstance(values, dict) or set(values) != FIELDS:
        raise ValueError("manual_settings_fields")
    for key, value in values.items():
        minimum = 0 if key in {"linear_speed", "turn_speed"} else 0.01 if key == "pulse_duration" else 0.001
        if not finite(value) or not minimum <= value <= cap[key]:
            raise ValueError("manual_settings_" + key)
    return dict(values)


def read():
    try:
        raw = path().read_bytes()
    except FileNotFoundError:
        return {"revision": 0, "values": defaults()}
    if len(raw) > 2048:
        raise ValueError("manual_settings_oversized")
    row = json.loads(raw)
    if not isinstance(row, dict) or type(row.get("revision")) is not int or row["revision"] < 1:
        raise ValueError("manual_settings_revision")
    return {"revision": row["revision"], "values": validate(row.get("values"))}


def snapshot():
    row = read()
    return dict(
        row,
        contract_id="rider.manual_settings",
        contract_version=1,
        observed_at=time.time(),
        limits=limits(),
        actuation=False,
    )


def update(patch, revision):
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(str(target) + ".lock", "a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = read()
        if type(revision) is not int or revision != current["revision"]:
            raise ValueError("manual_settings_conflict")
        if not isinstance(patch, dict) or not patch or set(patch) - FIELDS:
            raise ValueError("manual_settings_fields")
        values = validate(dict(current["values"], **patch))
        if values == current["values"]:
            return current
        row = {"revision": current["revision"] + 1, "values": values}
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".manual-controls-")
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(row, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return row


def pulse(row, direction):
    v = row["values"]
    axes = {
        "forward": (v["linear_speed"], 0),
        "backward": (-v["linear_speed"], 0),
        "left": (0, -v["turn_speed"]),
        "right": (0, v["turn_speed"]),
    }
    if direction not in axes:
        raise ValueError("manual_direction")
    vx, yaw = axes[direction]
    return {"vx": vx, "yaw": yaw, "duration": v["pulse_duration"]}
