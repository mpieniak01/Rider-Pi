"""Passive per-unit acceptance snapshots; never connect to hardware or BUS."""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path


def read_status(unit: str, max_age_s: float = 3.0, *, root: Path | None = None) -> dict:
    root = root or Path(os.getenv("FEATURE_STATE_PATH", "/run/rider-motion/feature_state.json")).parent
    path = root / (unit + ".json")
    try:
        if path.stat().st_size > 65536:
            raise ValueError("snapshot too large")
        status = json.loads(path.read_text(encoding="utf-8"))
        observed = status["observed_at"]
        if (
            not isinstance(status, dict)
            or status.get("unit") != unit
            or isinstance(observed, bool)
            or not isinstance(observed, (int, float))
            or not math.isfinite(observed)
            or not -0.1 <= time.time() - observed <= max_age_s
        ):
            raise ValueError("invalid or stale unit snapshot")
        return {**status, "stale": False}
    except (OSError, ValueError, TypeError, KeyError):
        return {
            "unit": unit,
            "accepted": False,
            "active": False,
            "ready": False,
            "stale": True,
            "error": "producer_acceptance_unavailable",
            "observed_at": None,
        }
