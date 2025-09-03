#!/usr/bin/env python3
import os, time, shutil, json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SNAP_DIR = Path(os.getenv("SNAP_DIR", BASE_DIR / "snapshots"))
DATA_DIR = BASE_DIR / "data"
LAST_OUT = DATA_DIR / "last_frame.jpg"
SOURCES = [SNAP_DIR / "proc.jpg", SNAP_DIR / "cam.jpg"]  # preferuj proc.jpg

os.makedirs(DATA_DIR, exist_ok=True)

# Opcjonalny ZMQ heartbeat (camera.heartbeat)
BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))
_pub = None
try:
    import zmq  # type: ignore
    _ctx = zmq.Context.instance()
    _pub = _ctx.socket(zmq.PUB)
    _pub.connect(f"tcp://127.0.0.1:{BUS_PUB_PORT}")
except Exception:
    _pub = None

def hb(fps=None):
    if not _pub: return
    try:
        payload = {"mode": "sink", "fps": None if fps is None else round(float(fps),1), "lcd": {"active": False}}
        _pub.send_string(f"camera.heartbeat {json.dumps(payload)}")
    except Exception:
        pass

def atomic_copy(src: Path, dst: Path):
    tmp = dst.with_suffix(".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)  # atomic

def main():
    last_mtime = 0.0
    last_copy_ts = None
    fps = None
    last_hb = 0.0

    while True:
        try:
            src = next((p for p in SOURCES if p.is_file()), None)
            if src:
                m = src.stat().st_mtime
                if m > last_mtime:
                    now = time.time()
                    atomic_copy(src, LAST_OUT)
                    if last_copy_ts is not None:
                        dt = max(1e-6, now - last_copy_ts)
                        fps = 1.0 / dt
                    last_copy_ts = now
                    last_mtime = m
            # HB co ~2 s
            t = time.time()
            if t - last_hb >= 2.0:
                hb(fps)
                last_hb = t
        except Exception:
            time.sleep(0.2)
        time.sleep(0.2)

if __name__ == "__main__":
    main()
