from __future__ import annotations

import time
from pathlib import Path

FLAGS_DIR = Path("data/flags")
LAST_FRAME = Path("data/last_frame.jpg")


def _flag_path(name: str) -> Path:
    return FLAGS_DIR / name


def _flag_on(name: str) -> bool:
    return _flag_path(name).exists()


def set_flag(name: str, on: bool) -> bool:
    FLAGS_DIR.mkdir(parents=True, exist_ok=True)
    p = _flag_path(name)
    try:
        if on:
            p.touch(exist_ok=True)
        else:
            if p.exists():
                p.unlink()
        return True
    except Exception:
        return False


def get_motion_flags():
    return {
        "motion_enable": _flag_on("motion.enable"),
        "estop": _flag_on("estop.on"),
    }


def get_last_frame_info():
    if LAST_FRAME.exists():
        return {
            "exists": True,
            "mtime": LAST_FRAME.stat().st_mtime,
            "path": str(LAST_FRAME),
        }
    return {"exists": False, "mtime": None, "path": str(LAST_FRAME)}


def get_bus_health():
    from . import compat as C
    from .bus_health import snapshot

    return snapshot(C)


def get_devices_summary():
    from .devices import xgo_snapshot

    xgo = xgo_snapshot()
    rows = xgo.get("observation", {}).get("sensor_quality", {}).get("sensors", {})
    return {
        "xgo": {
            "connected": True if any(row.get("ready") is True for row in rows.values()) else None,
            "last_telemetry_ts": xgo.get("observed_at"),
            "observation": xgo.get("observation"),
        },
        "vision": {"running": None, "last_frame": get_last_frame_info()},
        "bus": get_bus_health(),
        "flags": get_motion_flags(),
    }


def snapshot():
    return {
        "ts": time.time(),
        "generated_at": time.time(),
        "observed_at": None,
        "summary": get_devices_summary(),
    }
