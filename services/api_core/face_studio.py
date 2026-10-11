"""Face studio: common catalog, on-demand previews and explicit runtime controls."""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections import OrderedDict

from flask import Response, jsonify, request

from apps.ui.face.animator import Animator
from apps.ui.face.catalog import CATALOG, LOCK, descriptors, get_settings, save_settings, settings_revision
from apps.ui.face.renderer import FaceRenderer
from apps.ui.face.schema import FIELDS, number as _number, prepare, validate
from services.api_core.static_pages import serve_web

_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()
_RENDER_SLOT = threading.BoundedSemaphore(1)
_RENDERERS = {}
MAX_CACHED_FRAMES = 16


def page():
    return serve_web("face-studio.html")


def library():
    try:
        if request.method == "POST":
            key, spec = CATALOG.save(request.get_json(silent=True))
            return jsonify(ok=True, id=key, gesture=spec, actuation=False)
        return jsonify(
            ok=True,
            gestures=CATALOG.items(),
            fields=FIELDS,
            descriptors=descriptors(),
            settings=get_settings(),
            settings_revision=settings_revision(),
            revision=CATALOG.revision,
            actuation=False,
        )
    except (ValueError, TypeError, KeyError, OSError, OverflowError) as error:
        return jsonify(ok=False, error=str(error), actuation=False), 400


def delete(key):
    try:
        if not CATALOG.delete(key):
            return jsonify(ok=False, error="unknown_gesture"), 404
        return jsonify(ok=True, actuation=False)
    except (ValueError, OSError):
        return jsonify(ok=False, error="library_unavailable"), 400


def _preview(body):
    settings = get_settings()
    style = body.get("style", settings["style"])
    options = descriptors()
    if style not in {item["id"] for item in options["styles"]}:
        raise ValueError("invalid_face_style")
    spec = prepare(
        body, body.get("intensity", 1), body.get("tempo", 1), body.get("transition", "original"), defaults=True
    )
    at = round(_number(body.get("at", 0), 0, spec["duration"]), 3)
    simulated = body.get("simulate_speech", False)
    if type(simulated) is not bool:
        raise ValueError("invalid_speech_preview")
    identity = hashlib.sha256(json.dumps([spec, at, style, simulated], sort_keys=True).encode()).hexdigest()
    with _CACHE_LOCK:
        cached = _CACHE.get(identity)
        if cached is not None:
            _CACHE.move_to_end(identity)
            return cached
    if not _RENDER_SLOT.acquire(blocking=False):
        return None
    try:
        clock = [0.0]
        anim = Animator(clock=lambda: clock[0])
        anim.state.expr = spec["expr"]
        anim.state.mouth.shape = spec["expr"] if spec["expr"] in {"happy", "sad", "neutral"} else "neutral"
        anim.start(spec, mode="replace")
        clock[0] = at
        anim.tick()
        if simulated:
            anim.state.mouth.open = max(0, math.sin(at * 13)) * 0.65
        anim.state.render_time = at
        if style not in _RENDERERS:
            _RENDERERS[style] = FaceRenderer({}, size=240, style=style)
        renderer = _RENDERERS[style]
        png = renderer.render_png_bytes(anim.state)
        with _CACHE_LOCK:
            _CACHE[identity] = png
            while len(_CACHE) > MAX_CACHED_FRAMES:
                _CACHE.popitem(last=False)
        return png
    finally:
        _RENDER_SLOT.release()


def frame():
    try:
        if request.content_length and request.content_length > 65536:
            return jsonify(ok=False, error="gesture_too_large"), 413
        body = request.get_json(silent=True)
        validate(body)
        png = _preview(body)
        if png is None:
            return jsonify(ok=False, error="preview_busy"), 429, {"Retry-After": "1"}
        return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, OSError):
        return jsonify(ok=False, error="invalid_frame", actuation=False), 400


def runtime():
    from services.api_core import face_anim

    try:
        with LOCK:
            if request.method == "POST":
                body = request.get_json(silent=True)
                if not isinstance(body, dict):
                    raise ValueError("invalid_face_settings")
                save_settings(body, body.pop("if_revision", None))
            settings = get_settings()
            revision = settings_revision(settings)
        return jsonify(
            **face_anim.get_state(), settings=settings, settings_revision=revision, descriptors=descriptors()
        )
    except (ValueError, TypeError, KeyError, OSError) as error:
        conflict = str(error) == "face_settings_conflict"
        return jsonify(ok=False, error=str(error), actuation=False), 409 if conflict else 400


def runtime_play():
    from services.api_core import face_anim

    result = face_anim.play(request.get_json(silent=True) or {})
    return jsonify(result), result.get("status", 200)


def runtime_stop():
    from services.api_core import face_anim

    return jsonify(face_anim.stop())


def runtime_event():
    from services.api_core import face_anim

    try:
        return jsonify(face_anim.command(request.get_json(silent=True)))
    except (ValueError, TypeError, KeyError, OSError) as error:
        return jsonify(ok=False, error=str(error), actuation=False), 409


def runtime_frame():
    from services.api_core import face_anim

    png = face_anim.latest_png()
    if png is None:
        return jsonify(ok=False, error="face_not_running"), 404
    return Response(
        png, mimetype="image/png", headers={"Cache-Control": "no-store", "X-Face-Source": "active-face-worker"}
    )


def register(app):
    app.add_url_rule("/face-studio", "face_studio_page", page)
    app.add_url_rule("/api/face-studio/gestures", "face_studio_library", library, methods=["GET", "POST"])
    app.add_url_rule("/api/face-studio/gestures/<key>", "face_studio_delete", delete, methods=["DELETE"])
    app.add_url_rule("/api/face-studio/frame", "face_studio_frame", frame, methods=["POST"])
    app.add_url_rule("/api/face-studio/runtime", "face_studio_runtime", runtime, methods=["GET", "POST"])
    app.add_url_rule("/api/face-studio/runtime/play", "face_studio_runtime_play", runtime_play, methods=["POST"])
    app.add_url_rule("/api/face-studio/runtime/stop", "face_studio_runtime_stop", runtime_stop, methods=["POST"])
    app.add_url_rule("/api/face-studio/runtime/event", "face_studio_runtime_event", runtime_event, methods=["POST"])
    app.add_url_rule("/api/face-studio/runtime/frame", "face_studio_runtime_frame", runtime_frame)
