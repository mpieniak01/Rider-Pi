from __future__ import annotations
from pathlib import Path
import time

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
        return {"exists": True, "mtime": LAST_FRAME.stat().st_mtime, "path": str(LAST_FRAME)}
    return {"exists": False, "mtime": None, "path": str(LAST_FRAME)}

def get_bus_health():
    # TODO: wpiąć realny heartbeat z brokera (z busa lub pliku).
    return {"broker": "unknown", "last_seen_ts": None}

def get_devices_summary():
    return {
        "xgo": {"connected": None, "last_telemetry_ts": None},
        "vision": {"running": None, "last_frame": get_last_frame_info()},
        "bus": get_bus_health(),
        "flags": get_motion_flags(),
    }

def snapshot():
    return {
        "ts": time.time(),
        "summary": get_devices_summary(),
    }
