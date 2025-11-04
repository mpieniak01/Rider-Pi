#!/usr/bin/env python3
# robot/services/api_core/vision_api.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any

from flask import Blueprint, Response, jsonify, make_response, request, send_file

from common import bus

# Używamy stałych ścieżek z compat (RAW_PATH/PROC_PATH/SNAP_DIR, opcjonalnie DATA_DIR)
from services.api_core import compat as C

logger = logging.getLogger(__name__)
bp = Blueprint("vision_api", __name__)

# ---------- helpers: nagłówki / ścieżki ----------


def _nocache(resp: Response) -> Response:
    """Twardo wyłącz cache po stronie klienta/przeglądarki."""
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


def _json_nocache(payload: Any, status: int = 200) -> Response:
    """JSON z nagłówkami no-store."""
    resp = make_response(jsonify(payload), status)
    return _nocache(resp)


def _ssd_path() -> str:
    return os.getenv("SSD_PATH", os.path.join(C.SNAP_DIR, "ssd.jpg"))


# ---------- helpers: obrazy ----------


def _img_response(path: str) -> Response:
    """Zwróć obraz z wyłączonym cache; nie rzucaj 500 dla HEAD/GET."""
    if not os.path.isfile(path):
        # spójny 404 (text/plain — brak pliku)
        resp = make_response(f"Not found: {path}", 404)
        resp.headers["Content-Type"] = "text/plain; charset=utf-8"
        return _nocache(resp)
    # jeżeli plik istnieje — serwuj bezwarunkowo (HEAD otrzyma 200 bez body)
    resp = send_file(path, mimetype="image/jpeg", conditional=True)
    return _nocache(resp)


@bp.route("/vision/cam", methods=["GET", "HEAD"])
def vision_cam() -> Response:
    return _img_response(C.RAW_PATH)


@bp.route("/vision/edge", methods=["GET", "HEAD"])
def vision_edge() -> Response:
    return _img_response(C.PROC_PATH)


@bp.route("/vision/ssd", methods=["GET", "HEAD"])
def vision_ssd() -> Response:
    return _img_response(_ssd_path())


@bp.route("/vision/tracker", methods=["GET", "HEAD"])
def vision_tracker() -> Response:
    """Serve tracker annotated frame (FPS + detection circle)."""
    tracker_path = os.path.join(C.SNAP_DIR, "tracker.jpg")
    return _img_response(tracker_path)


# ---------- meta: snap-info ----------


@bp.route("/vision/snap-info", methods=["GET", "HEAD"])
def snap_info() -> Response:
    def info(p: str):
        try:
            st = os.stat(p)
            with open(p, "rb") as f:
                md5 = hashlib.md5(f.read()).hexdigest()
            now = time.time()
            return {
                "exists": True,
                "path": p,
                "mtime": int(st.st_mtime),
                "size": st.st_size,
                "md5": md5,
                "age_s": round(max(0.0, now - float(st.st_mtime)), 3),
            }
        except FileNotFoundError:
            return {"exists": False, "path": p}

    payload = {
        "raw": info(C.RAW_PATH),
        "proc": info(C.PROC_PATH),
        "ssd": info(_ssd_path()),
        "tracker": info(os.path.join(C.SNAP_DIR, "tracker.jpg")),
    }
    return _json_nocache(payload, 200)


# ---------- helpers: obstacle (kompatybilność dla state_api) ----------


def _default_data_dir() -> str:
    # Jeśli compat ma DATA_DIR — użyj. W przeciwnym razie: ~/robot/data obok snapshots.
    if hasattr(C, "DATA_DIR"):
        return C.DATA_DIR  # type: ignore[attr-defined]
    base = os.path.dirname(C.SNAP_DIR)
    return os.path.join(base, "data")


def load_obstacle() -> dict[str, Any]:
    """
    Kompatybilna funkcja używana przez state_api.
    Źródło: plik JSON, domyślnie data/obstacle.json (można nadpisać przez ENV).
    Zwraca słownik z co najmniej kluczem 'present' (bool).
    """
    data_dir = os.getenv("DATA_DIR", _default_data_dir())
    path = os.getenv("OBSTACLE_JSON", os.path.join(data_dir, "obstacle.json"))

    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        # twardy fallback kluczy, by uniknąć KeyError downstream
        if not isinstance(payload, dict):
            return {"present": False, "error": "invalid_json_type", "path": path}
        payload.setdefault("present", False)
        return payload
    except FileNotFoundError:
        return {"present": False, "error": "not_found", "path": path}
    except json.JSONDecodeError as e:
        return {"present": False, "error": f"json_decode:{e}", "path": path}
    except Exception as e:
        return {"present": False, "error": f"unexpected:{e}", "path": path}


@bp.route("/vision/obstacle", methods=["GET", "HEAD"])
def vision_obstacle() -> Response:
    """Publiczny endpoint z aktualnym stanem przeszkody (do UI i diagnostyki)."""
    return _json_nocache(load_obstacle(), 200)


# ---------- Follow Me tracking control endpoints ----------


@bp.route("/vision/tracking/mode", methods=["POST", "OPTIONS"])
def set_tracking_mode() -> Response:
    """
    Unified tracking mode control endpoint.
    Payload: {"mode": "face"|"hand"|"none", "enabled": true|false}
    
    If enabled=false, mode is automatically set to "none".
    """
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    try:
        payload = request.get_json(silent=True) or {}
        mode = payload.get("mode", "none").lower()
        enabled = payload.get("enabled", True)
        
        # If enabled=false, override mode to "none"
        if not enabled:
            mode = "none"
        
        # Validate mode
        if mode not in ["face", "hand", "none"]:
            return _json_nocache(
                {"ok": False, "error": f"Invalid mode: {mode}. Must be 'face', 'hand', or 'none'."},
                400
            )

        # Publish to unified topic
        pub = bus.BusPub()
        pub.publish(bus.TOPIC_TRACKING_MODE_SET, {"mode": mode}, add_ts=True)
        pub.close()

        return _json_nocache({"ok": True, "mode": mode, "enabled": (mode != "none")}, 200)
    except Exception as e:
        logger.exception("Failed to set tracking mode: %s", e)
        return _json_nocache({"ok": False, "error": "Failed to set tracking mode"}, 500)


@bp.route("/vision/follow/face", methods=["POST", "OPTIONS"])
def set_follow_face() -> Response:
    """Enable or disable face tracking mode."""
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    try:
        payload = request.get_json(silent=True) or {}
        enable = payload.get("enable", False)

        pub = bus.BusPub()
        if enable:
            pub.publish(bus.TOPIC_VISION_FOLLOW_FACE_SET, {"enabled": True})
        else:
            pub.publish(bus.TOPIC_VISION_FOLLOW_STOP, {"mode": "face"})
        pub.close()

        return _json_nocache({"ok": True, "mode": "face", "enabled": enable}, 200)
    except Exception as e:
        logger.exception("Failed to set face tracking mode: %s", e)
        return _json_nocache({"ok": False, "error": "Failed to set face tracking mode"}, 500)


@bp.route("/vision/follow/hand", methods=["POST", "OPTIONS"])
def set_follow_hand() -> Response:
    """Enable or disable hand tracking mode."""
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    try:
        payload = request.get_json(silent=True) or {}
        enable = payload.get("enable", False)

        pub = bus.BusPub()
        if enable:
            pub.publish(bus.TOPIC_VISION_FOLLOW_HAND_SET, {"enabled": True})
        else:
            pub.publish(bus.TOPIC_VISION_FOLLOW_STOP, {"mode": "hand"})
        pub.close()

        return _json_nocache({"ok": True, "mode": "hand", "enabled": enable}, 200)
    except Exception as e:
        logger.exception("Failed to set hand tracking mode: %s", e)
        return _json_nocache({"ok": False, "error": "Failed to set hand tracking mode"}, 500)
