"""Read-only transport readiness from received traffic and the executor heartbeat."""

from __future__ import annotations

import math
import time


def _age(value, now):
    if type(value) not in {int, float}:
        return None
    try:
        age = now - value
        return age if value > 0 and math.isfinite(value) and math.isfinite(age) and age >= -0.1 else None
    except OverflowError:
        return None


def snapshot(C, *, now=None, safety=None) -> dict:
    now = time.time() if now is None else now
    msg_at = getattr(C, "LAST_MSG_TS", None)
    hb_at = getattr(C, "LAST_HEARTBEAT_TS", None)
    msg_age = _age(msg_at, now)
    hb_age = _age(hb_at, now)
    available = getattr(C, "_ZMQ_OK", False) is True
    connected = available and msg_age is not None and msg_age <= 30
    if safety is None:
        from services.safety_contract import read_status

        safety = read_status()
    safety_age = _age(safety.get("observed_at"), now)
    executor_live = (
        safety_age is not None
        and safety_age <= 3
        and safety.get("stale") is not True
        and safety.get("offline") is not True
        and bool(safety.get("instance_id"))
    )
    bus = {
        "connected": connected,
        "ready": connected,
        "available": available,
        "source": "api-bus-subscriber",
        "observed_at": None,
        "transport": {"received_at": msg_at if msg_age is not None else None},
        "last_msg_age_s": msg_age,
        "last_heartbeat_age_s": hb_age,
        "stale": not connected,
        "error": None if connected else "bus_traffic_unavailable",
    }
    ready = connected and executor_live
    return {
        "ok": True,
        "source": "pi",
        "observed_at": None,
        "api": {"live": True},
        "ready": ready,
        "ready_hint": ready,
        "bus": bus,
        "components": {
            "bus": bus,
            "executor": {
                "live": executor_live,
                "ready": executor_live,
                "source": "motion-executor",
                "observed_at": safety.get("observed_at"),
                "instance_id": safety.get("instance_id"),
                "stale": not executor_live,
                "error": None if executor_live else "executor_heartbeat_unavailable",
            },
        },
        "partial": not ready,
        "zmq_available": available,
        "zmq": {"available": available},
        "last_msg_age_s": msg_age,
        "last_heartbeat_age_s": hb_age,
        "ports": {"pub": getattr(C, "BUS_PUB_PORT", None), "sub": getattr(C, "BUS_SUB_PORT", None)},
    }
