#!/usr/bin/env python3
# robot/services/api_core/vision_api.py
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from typing import Any

from flask import Blueprint, Response, jsonify, make_response, request

from common import bus

# Używamy stałych ścieżek z compat (RAW_PATH/PROC_PATH/SNAP_DIR, opcjonalnie DATA_DIR)
from services.api_core import compat as C, frames
from services.api_core.http_contract import canonical_data, negotiated
from services.api_core.http_security import apply_cors

logger = logging.getLogger(__name__)
bp = Blueprint("vision_api", __name__)

_TRACKING_PUB = None
_TRACKING_PUB_LOCK = threading.Lock()


def _tracking_pub() -> bus.BusPub:
    global _TRACKING_PUB
    if _TRACKING_PUB is None:
        with _TRACKING_PUB_LOCK:
            if _TRACKING_PUB is None:
                _TRACKING_PUB = bus.BusPub()
    return _TRACKING_PUB


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
    stream = next((name for name in frames.STREAMS if str(frames.resolve(name)) == path), "raw")
    return frames.response(stream, path=path)


@bp.route("/vision/cam", methods=["GET", "HEAD"])
def vision_cam() -> Response:
    return frames.response("raw")


@bp.route("/vision/edge", methods=["GET", "HEAD"])
def vision_edge() -> Response:
    return frames.response("proc")


@bp.route("/vision/ssd", methods=["GET", "HEAD"])
def vision_ssd() -> Response:
    return frames.response("ssd")


@bp.route("/vision/tracker", methods=["GET", "HEAD"])
def vision_tracker() -> Response:
    """Serve tracker annotated frame (FPS + detection circle)."""
    return frames.response("tracker")


@bp.route("/vision/obst", methods=["GET", "HEAD"])
def vision_obst() -> Response:
    return frames.response("obst")


# ---------- meta: snap-info ----------


@bp.route("/vision/snap-info", methods=["GET", "HEAD"])
def snap_info() -> Response:
    payload = {name: {**frames.describe(name), "md5": None} for name in frames.STREAMS}
    if negotiated():
        canonical_data(payload)
        return _json_nocache(payload, 200)
    legacy = {}
    for name, row in payload.items():
        value = {
            "exists": row["exists"],
            "path": row["path"],
            "source": row["source"],
            "provenance": row["provenance"],
            "stale": row["stale"],
            "error": row["error"],
        }
        if row["exists"]:
            digest = None
            if request.args.get("light") != "1" and row["source"] == "filesystem":
                try:
                    with open(row["path"], "rb") as stream:
                        digest = hashlib.md5(stream.read(), usedforsecurity=False).hexdigest()
                except OSError:
                    value.update(stale=True, error="frame_unavailable")
            value.update(mtime=row["mtime"], size=row["size"], md5=digest, age_s=row["age_s"])
        legacy[name] = value
    return _json_nocache(legacy, 200)


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


@bp.route("/vision/tracking/mode", methods=["GET", "POST", "OPTIONS"])
def set_tracking_mode() -> Response:
    """
    Unified tracking mode control endpoint.
    Payload: {"mode": "face"|"hand"|"none", "enabled": true|false}

    If enabled=false, mode is automatically set to "none".
    """
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        apply_cors(resp)
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    try:
        from .features_api import feature_manager

        if request.method == "GET":
            task = next(row for row in feature_manager.describe_features() if row["name"] == "s6_tracker_module")
            mode = task["tracking_mode"] if task["requested"] else "none"
            return _json_nocache({"ok": True, "mode": mode, "enabled": task["requested"], "task": task})
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _json_nocache({"ok": False, "error": "JSON_object_required"}, 400)
        raw_mode = payload.get("mode", "none")
        if not isinstance(raw_mode, str):
            return _json_nocache({"ok": False, "error": "invalid_mode"}, 400)
        enabled = payload.get("enabled", raw_mode.lower() in ["face", "hand"])
        if not isinstance(enabled, bool):
            return _json_nocache({"ok": False, "error": "enabled_must_be_boolean"}, 400)
        mode = raw_mode.lower()

        # Validate mode before applying enabled override
        if mode not in ["face", "hand", "none"]:
            return _json_nocache(
                {
                    "ok": False,
                    "error": (f"Invalid mode: {mode}. Must be 'face', 'hand', or 'none'."),
                },
                400,
            )

        # If enabled=false, override mode to "none"
        if not enabled:
            mode = "none"

        result = feature_manager.set_feature("s6_tracker_module", mode != "none", options={"mode": mode})
        ok = result.get("ok") is True
        status = 200
        if not ok:
            status = 409 if result.get("error") in {"resource_conflict", "stop_before_reconfigure"} else 503
        return _json_nocache(
            {
                "ok": ok,
                "mode": mode,
                "enabled": (mode != "none"),
                "result": result,
                "blocked_by": result.get("blocked_by", result.get("consumers", [])),
                "error": result.get("error"),
            },
            status,
        )
    except Exception as e:
        logger.exception("Failed to set tracking mode: %s", e)
        return _json_nocache(
            {"ok": False, "error": "Failed to set tracking mode"},
            500,
        )


# ---------- Legacy Follow Me aliases (backward compatibility) ----------


@bp.route("/vision/follow/face", methods=["POST", "OPTIONS"])
def legacy_follow_face() -> Response:
    """Legacy endpoint usunięty – użyj /api/logic/feature/<name>."""
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        apply_cors(resp)
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp
    return _json_nocache({"ok": False, "error": "deprecated", "use": "/api/logic/feature"}, 410)


@bp.route("/vision/follow/hand", methods=["POST", "OPTIONS"])
def legacy_follow_hand() -> Response:
    """Legacy endpoint usunięty – użyj /api/logic/feature/<name>."""
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        apply_cors(resp)
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp
    return _json_nocache({"ok": False, "error": "deprecated", "use": "/api/logic/feature"}, 410)
