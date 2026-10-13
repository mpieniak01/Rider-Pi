"""One device-owned persisted policy; saving never starts a service."""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

from services.compute_config import _lock, _require_idle_goals, _selection_lock, _write

DEFAULT = {
    "protocol_version": 1,
    "revision": 0,
    "mode": "observe",
    "speed": 0.1,
    "decision_budget_ms": 300,
    "max_motion_ms": 150,
    "corridor": [0.35, 0.65, 0.65, 0.95],
    "verified": False,
    "calibration_id": "",
    "model_sha256": "",
}


def path():
    return Path(os.getenv("RIDER_NAVIGATION_CONFIG", "data/navigation_config.json"))


def validate(data):
    if not isinstance(data, dict) or set(data) != set(DEFAULT):
        raise ValueError("navigation_configuration_invalid")
    if (
        type(data["protocol_version"]) is not int
        or data["protocol_version"] != 1
        or type(data["revision"]) is not int
        or data["revision"] < 0
    ):
        raise ValueError("navigation_configuration_invalid")
    if data["mode"] not in {"observe", "drive"} or type(data["verified"]) is not bool:
        raise ValueError("navigation_configuration_invalid")
    speed = data["speed"]
    if (
        isinstance(speed, bool)
        or not isinstance(speed, (float, int))
        or not math.isfinite(speed)
        or not 0 < speed <= 0.15
    ):
        raise ValueError("navigation_speed_invalid")
    if type(data["decision_budget_ms"]) is not int or not 100 <= data["decision_budget_ms"] <= 500:
        raise ValueError("navigation_deadline_invalid")
    if type(data["max_motion_ms"]) is not int or not 50 <= data["max_motion_ms"] <= 200:
        raise ValueError("navigation_duration_invalid")
    roi = data["corridor"]
    if (
        not isinstance(roi, list)
        or len(roi) != 4
        or any(type(v) not in (float, int) or not math.isfinite(v) for v in roi)
    ):
        raise ValueError("navigation_corridor_invalid")
    x0, y0, x1, y1 = roi
    if not 0 <= x0 < x1 <= 1 or not 0 <= y0 < y1 <= 1:
        raise ValueError("navigation_corridor_invalid")
    if not isinstance(data["calibration_id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{0,64}", data["calibration_id"]):
        raise ValueError("navigation_calibration_invalid")
    if not isinstance(data["model_sha256"], str) or not re.fullmatch(r"(?:[a-f0-9]{64})?", data["model_sha256"]):
        raise ValueError("navigation_model_invalid")
    if data["mode"] == "drive" and (not data["verified"] or not data["calibration_id"] or not data["model_sha256"]):
        raise ValueError("navigation_validation_required")
    return data


def snapshot():
    p = path()
    if not p.exists():
        return json.loads(json.dumps(DEFAULT))
    if p.stat().st_size > 4096:
        raise ValueError("navigation_configuration_invalid")
    return validate(json.loads(p.read_text()))


def configure(body):
    if (
        not isinstance(body, dict)
        or set(body) != {"revision", "values"}
        or type(body["revision"]) is not int
        or not isinstance(body["values"], dict)
    ):
        raise ValueError("navigation_configuration_invalid")
    if set(body["values"]) - (set(DEFAULT) - {"protocol_version", "revision"}):
        raise ValueError("navigation_configuration_invalid")
    with _selection_lock(), _lock(path()):
        old = snapshot()
        if body["revision"] != old["revision"]:
            raise ValueError("navigation_configuration_conflict")
        _require_idle_goals()
        data = validate({**old, **body["values"], "revision": old["revision"] + 1})
        _write(path(), data)
    return data
