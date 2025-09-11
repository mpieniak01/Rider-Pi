from __future__ import annotations
import os, json, time
from pathlib import Path
from typing import Optional, Dict, Any
from flask import Blueprint, jsonify, abort, send_file

vision_bp = Blueprint("vision", __name__)

ROOT = Path(os.environ.get("RIDER_ROOT", "/home/pi/robot"))
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT / "data")))
SNAP_DIR = Path(os.environ.get("SNAP_DIR", str(ROOT / "snapshots")))
OBST_PATH = Path(os.environ.get("OBST_PATH", str(DATA_DIR / "obstacle.json")))

def load_obstacle() -> Optional[Dict[str, Any]]:
    try:
        if not OBST_PATH.exists():
            return None
        st = OBST_PATH.stat()
        data = json.loads(OBST_PATH.read_text() or "{}")
        ts = float(data.get("ts", st.st_mtime))
        data["ts"] = ts
        data["age_s"] = max(0.0, time.time() - ts)
        return data
    except Exception:
        return None

@vision_bp.route("/obstacle", methods=["GET"])
def obstacle():
    ob = load_obstacle()
    if not ob:
        return jsonify({"error": "no obstacle data"}), 404
    return jsonify(ob), 200

@vision_bp.route("/edge", methods=["GET"])
def edge_preview():
    p = SNAP_DIR / "proc.jpg"
    if not p.exists():
        abort(404)
    return send_file(str(p), mimetype="image/jpeg", conditional=True, etag=True)
