from __future__ import annotations

import json
import time

from flask import Response, jsonify

from common.observations import source_time
from services.api_core import compat
from services.api_core.devices import xgo_snapshot
from services.api_core.frames import describe as describe_frame
from services.api_core.navigation_state import snapshot as navigation_snapshot
from services.api_core.vision_api import load_obstacle  # reużywamy jednej logiki


def state() -> Response:
    """Return basic robot state information."""
    now = time.time()
    ts = compat.LAST_STATE.get("ts")
    age = (now - ts) if ts else None
    # Same file resolver as the image route; file mtime is an artifact time,
    # never a camera measurement or proof that the capture service is running.
    frame = describe_frame("raw", now=now)
    raw_ts = frame["file_observed_at"]
    cache_bust = int(raw_ts or now)
    camera_at = source_time(compat.LAST_CAMERA.get("ts"))
    camera_age = now - camera_at if camera_at is not None else None

    from services.core.camera_state import snapshot as camera_snapshot

    camera_activity = camera_snapshot(heartbeat=compat.LAST_CAMERA)
    now = time.time()
    xgo = xgo_snapshot(now=now)
    has_telemetry = xgo["present"]
    tracking_mode = compat.LAST_TRACKING_MODE
    tracking_offset = compat.LAST_TRACKING_OFFSET
    offset_ts = tracking_offset.get("ts")
    offset_age = round(now - offset_ts, 3) if offset_ts else None

    resp = {
        "present": bool(compat.LAST_STATE.get("present", False)),
        "confidence": float(compat.LAST_STATE.get("confidence", 0.0)),
        "mode": compat.LAST_STATE.get("mode"),
        "ts": ts,
        "age_s": round(age, 3) if age is not None else None,
        "source": "pi-telemetry-cache",
        "observed_at": xgo.get("observed_at"),
        "partial": xgo["observation"]["partial"],
        # A camera/domain fault is not a transport failure of independent XGO
        # measurements. Legacy vision fields above retain their original ts.
        "vision": {
            "state": {
                "source": compat.LAST_STATE.get("source", "vision.state"),
                "observed_at": ts,
                "stale": compat.LAST_STATE.get("stale") is True or age is None or not 0 <= age <= 3,
                "offline": compat.LAST_STATE.get("offline") is True,
                "error": compat.LAST_STATE.get("error"),
            }
        },
        "camera": {
            "activity": camera_activity,
            "vision_enabled": compat.LAST_CAMERA.get("vision_enabled"),
            "has_last_frame": frame["exists"],
            "last_frame_ts": int(raw_ts) if raw_ts else None,
            "preview_url": f"/camera/last?t={cache_bust}",
            "placeholder_url": "/camera/placeholder",
            "frame": frame,
            "source": compat.LAST_CAMERA.get("source", "camera.heartbeat"),
            "observed_at": camera_at,
            "age_s": camera_age,
            "capture_at": compat.LAST_CAMERA.get("capture_at"),
            "frame_id": compat.LAST_CAMERA.get("frame_id"),
            "stale": compat.LAST_CAMERA.get("stale") is True or camera_age is None or not 0 <= camera_age <= 5,
            "offline": compat.LAST_CAMERA.get("offline") is True,
            "error": compat.LAST_CAMERA.get("error"),
        },
        "devices": {"xgo": xgo if has_telemetry else None},
        "tracking": {
            "mode": tracking_mode.get("mode"),
            "enabled": tracking_mode.get("enabled"),
            "ts": tracking_mode.get("ts"),
            "offset": tracking_offset.get("offset"),
            "offset_mode": tracking_offset.get("mode"),
            "offset_ts": offset_ts,
            "offset_age_s": offset_age,
        },
        "navigation": navigation_snapshot(),
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
