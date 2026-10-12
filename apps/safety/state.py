"""Atomic executor snapshots. Reading this module never opens UART or BUS."""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from pathlib import Path

CONTRACT_VERSION = 1


def status_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    override = os.getenv("MOTION_STATE_PATH")
    if override:
        return Path(override)
    runtime = Path("/run/rider-motion")
    return runtime / "status.json" if runtime.is_dir() else root / "data" / "motion" / "status.json"


def read_status(max_age_s: float = 3.0) -> dict:
    unknown = {
        "contract_version": CONTRACT_VERSION,
        "state": "UNKNOWN",
        "ready": False,
        "can_move": False,
        "read_only": True,
        "observed_at": None,
        "owner": None,
        "execution_context": None,
        "panel_motion_enabled": False,
        "test_motion_enabled": False,
        "generation": None,
        "agent_epoch": None,
        "agent_last_seq": -1,
        "agent_manual_active": False,
        "manual_agent_grace_remaining_s": 0,
        "hardware_ready": False,
        "error": "executor_unavailable",
        "last_ack": None,
        "stale": True,
    }
    try:
        path = status_path()
        if path.stat().st_size > 65536:
            raise ValueError("snapshot too large")
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("contract_version") != CONTRACT_VERSION:
            raise ValueError("unsupported contract")
        observed = float(state["observed_at"])
        age = time.time() - observed
        if not math.isfinite(observed) or age < -0.1 or age > max_age_s:
            unknown.update(observed_at=observed, error="executor_stale")
            return unknown
        if state.get("state") not in {"DISARMED", "ARMED", "ESTOP"}:
            raise ValueError("unknown executor state")
        result = dict(state)
        result.update(stale=False, age_s=max(0.0, age))
        operator_armed = (
            state.get("arming_mode") == "operator"
            and state.get("execution_context") == "panel"
            and state.get("owner") == "manual"
        )
        lease = state.get("lease_remaining_s", 0)
        if not operator_armed and (
            isinstance(lease, bool) or not isinstance(lease, (int, float)) or not math.isfinite(lease) or lease < 0
        ):
            raise ValueError("invalid consent lease")
        result["can_move"] = bool(
            state.get("ready") is True
            and state.get("hardware_ready") is True
            and state.get("state") == "ARMED"
            and state.get("can_move") is True
        )
        if result["can_move"] and not operator_armed and age >= lease:
            result["can_move"] = False
            result["reason"] = "consent_expired_since_snapshot"
        result["read_only"] = not result["can_move"]
        context = state.get("execution_context", "panel")
        result["panel_motion_enabled"] = result["can_move"] and context == "panel"
        result["test_motion_enabled"] = result["can_move"] and context == "test"
        return result
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return unknown


def write_status(state: dict) -> None:
    """Called only by the sole executor. Atomic replacement avoids partial reads."""
    atomic_write(status_path(), state)


def atomic_write(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".status-", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
