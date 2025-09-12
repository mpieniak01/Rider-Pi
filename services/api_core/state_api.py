from __future__ import annotations
import json, os, time
from flask import jsonify, Response
from services.api_core import compat
from services.api_core.vision_api import load_obstacle  # reużywamy jednej logiki


def state() -> Response:
    now = time.time()
    ts = compat.LAST_STATE.get("ts")
    age = (now - ts) if ts else None
    raw_ts = None
    try:
        st = os.stat(compat.RAW_PATH)
        raw_ts = float(st.st_mtime)
    except Exception:
        pass
    fresh = (raw_ts is not None and (now - float(raw_ts)) <= float(os.getenv("LAST_FRESH_S", "3")))
    vision_enabled = bool((os.getenv("VISION_ENABLED", "0") == "1") or fresh)
    cache_bust = int(raw_ts or now)

    inferred_pose = compat.LAST_XGO.get("pose") or compat._classify_pose(
        compat.LAST_XGO.get("roll"), compat.LAST_XGO.get("pitch")
    )

    resp = {
        "present": bool(compat.LAST_STATE.get("present", False)),
        "confidence": float(compat.LAST_STATE.get("confidence", 0.0)),
        "mode": compat.LAST_STATE.get("mode"),
        "ts": ts,
        "age_s": round(age, 3) if age is not None else None,
        "camera": {
            "vision_enabled": vision_enabled,
            "has_last_frame": bool(raw_ts),
            "last_frame_ts": int(raw_ts) if raw_ts else None,
            "preview_url": f"/camera/last?t={cache_bust}",
            "placeholder_url": "/camera/placeholder",
        },
        "devices": {
            "xgo": (
                {
                    "present": True,
                    "imu_ok": compat.LAST_XGO.get("imu_ok"),
                    "pose": inferred_pose,
                    "battery_pct": compat.LAST_XGO.get("battery"),
                    "roll": compat.LAST_XGO.get("roll"),
                    "pitch": compat.LAST_XGO.get("pitch"),
                    "yaw": compat.LAST_XGO.get("yaw"),
                    "fw": compat.XGO_FW,
                    "ts": compat.LAST_XGO.get("ts"),
                }
                if compat.LAST_XGO.get("ts")
                else None
            )
        },
    }
    return Response(json.dumps(resp), mimetype="application/json")


def state_route():
    """Deleguje do state() i dokleja vision.obstacle (jeśli dostępne)."""
    base_resp = state()
    status = getattr(base_resp, "status_code", 200)

    payload = None
    get_json = getattr(base_resp, "get_json", None)
    if callable(get_json):
        payload = base_resp.get_json(silent=True)
    if payload is None:
        try:
            payload = json.loads(base_resp.get_data(as_text=True) or "{}")
        except Exception:
            payload = {}

    obst = load_obstacle()
    if obst:
        payload.setdefault("vision", {})["obstacle"] = obst

    return jsonify(payload), status
