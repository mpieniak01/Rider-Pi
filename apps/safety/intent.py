"""Read only the task authorization journal; never start services or hardware."""

from __future__ import annotations

import fcntl
import json
import math
import os
import time
import uuid
from pathlib import Path

from apps.safety.state import atomic_write

PRODUCERS = frozenset(
    {"rider-navigator.service", "rider-tracking-controller.service", "rider-venom-navigation.service"}
)
_PRODUCER_INSTANCE = uuid.uuid4().hex


def read_service_intent(unit: str, generation: str | None) -> dict | None:
    if not generation:
        return None
    path = Path(os.getenv("FEATURE_STATE_PATH", "/run/rider-motion/feature_state.json"))
    try:
        if path.stat().st_size > 262144:
            return None
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        intent = snapshot.get("service_intents", {}).get(unit)
        if not isinstance(intent, dict) or intent.get("generation") != generation:
            return None
        if not isinstance(intent.get("request_id"), str) or not intent["request_id"]:
            return None
        seq, ts = intent.get("seq"), intent.get("ts")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
            return None
        if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts):
            return None
        return dict(intent)
    except (OSError, ValueError, TypeError, AttributeError, OverflowError):
        return None


def write_intent_status(
    unit: str,
    intent: dict,
    *,
    active: bool,
    accepted: bool = True,
    data_ready=None,
    navigation_ready=None,
    data_error=None,
) -> bool:
    if unit not in PRODUCERS:
        return False
    root = Path(os.getenv("FEATURE_STATE_PATH", "/run/rider-motion/feature_state.json")).parent
    status = {
        "unit": unit,
        "generation": intent.get("generation"),
        "request_id": intent.get("request_id"),
        "accepted": accepted,
        "active": active,
        "observed_at": time.time(),
        "instance_id": _PRODUCER_INSTANCE,
        "pid": os.getpid(),
    }
    for key, value in (("data_ready", data_ready), ("navigation_ready", navigation_ready)):
        if type(value) is bool:
            status[key] = value
    if data_error is not None:
        status["data_error"] = str(data_error)[:256]
    try:
        root.mkdir(parents=True, exist_ok=True)
        path = root / (unit + ".json")
        with (root / (unit + ".claim.lock")).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if path.exists():
                if path.stat().st_size > 65536:
                    return False
                previous = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(previous, dict):
                    return False
                same_task = all(previous.get(k) == status[k] for k in ("generation", "request_id"))
                if same_task and previous.get("instance_id") != _PRODUCER_INSTANCE:
                    return False
            atomic_write(path, status)
        return True
    except (OSError, ValueError, TypeError):
        return False
