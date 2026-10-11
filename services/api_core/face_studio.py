"""Hardware-free face studio using the production renderer and animator."""

import json
import math
import os
import tempfile
import threading
import uuid
from pathlib import Path

from flask import Response, jsonify, request

from apps.ui.face.animator import Animator
from apps.ui.face.gestures import GESTURES
from apps.ui.face.renderer import FaceRenderer
from services.api_core.static_pages import serve_web

FIELDS = {
    "eyes.dx": (-1, 1),
    "eyes.dy": (-1, 1),
    "eyes.blink": (0, 1),
    "brows.lift": (-1, 1),
    "brows.tilt": (-1, 1),
    "mouth.open": (0, 1),
}
EXPRESSIONS = {"neutral", "happy", "sad"}
EASING = {"lin", "in", "out", "in_out"}
_lock = threading.Lock()


def _path():
    return Path(os.environ.get("FACE_STUDIO_LIBRARY", "config/local/face-studio.json"))


def _number(value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid_number")
    value = float(value)
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError("value_out_of_range")
    return value


def validate(body):
    if not isinstance(body, dict):
        raise ValueError("invalid_gesture")
    name = body.get("name", "")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
        raise ValueError("name_required")
    expr = body.get("expr", "neutral")
    if not isinstance(expr, str) or expr not in EXPRESSIONS:
        raise ValueError("invalid_expression")
    duration = _number(body.get("duration", 1), 0.05, 10)
    initial, tracks = body.get("initial", {}), body.get("tracks", {})
    if not isinstance(initial, dict) or not isinstance(tracks, dict):
        raise ValueError("invalid_tracks")
    clean_initial, clean_tracks = {}, {}
    for field, value in initial.items():
        if field not in FIELDS:
            raise ValueError("invalid_field")
        clean_initial[field] = _number(value, *FIELDS[field])
    for field, segments in tracks.items():
        if field not in FIELDS or not isinstance(segments, list) or len(segments) > 32:
            raise ValueError("invalid_track")
        clean_tracks[field] = []
        end = 0
        for segment in segments:
            if not isinstance(segment, dict):
                raise ValueError("invalid_segment")
            t0 = _number(segment["t0"], end, duration)
            t1 = _number(segment["t1"], t0, duration)
            ease = segment.get("ease", "lin")
            if t1 <= t0 or not isinstance(ease, str) or ease not in EASING:
                raise ValueError("invalid_segment")
            clean_tracks[field].append(
                {
                    "t0": t0,
                    "t1": t1,
                    "v0": _number(segment["v0"], *FIELDS[field]),
                    "v1": _number(segment["v1"], *FIELDS[field]),
                    "ease": ease,
                }
            )
            end = t1
    return {"name": name.strip(), "expr": expr, "duration": duration, "initial": clean_initial, "tracks": clean_tracks}


def _read():
    path = _path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or len(data) > 200:
        raise ValueError("invalid_library")
    return data


def _write(data):
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".face-studio-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _builtins():
    result = []
    for name, make in GESTURES.items():
        result.append({"id": "builtin:" + name, "builtin": True, **validate({**make(), "expr": "neutral"})})
    for expr in ("neutral", "happy", "sad"):
        result.append(
            {"id": "builtin:" + expr, "builtin": True, **validate({"name": expr, "expr": expr, "duration": 1})}
        )
    return result


def page():
    return serve_web("face-studio.html")


def library():
    try:
        with _lock:
            data = _read()
            if request.method == "POST":
                body = request.get_json(silent=True)
                spec = validate(body)
                key = body.get("id")
                if key and (not isinstance(key, str) or key not in data):
                    raise ValueError("unknown_gesture")
                if not key and len(data) >= 200:
                    raise ValueError("library_full")
                key = key or uuid.uuid4().hex
                data[key] = spec
                _write(data)
                return jsonify(ok=True, id=key, gesture=spec, actuation=False)
            return jsonify(
                ok=True,
                gestures=_builtins() + [{"id": key, "builtin": False, **validate(spec)} for key, spec in data.items()],
                fields=FIELDS,
                actuation=False,
            )
    except (ValueError, TypeError, KeyError, OSError, OverflowError) as error:
        return jsonify(ok=False, error=str(error), actuation=False), 400


def delete(key):
    try:
        with _lock:
            data = _read()
            if key not in data:
                return jsonify(ok=False, error="unknown_gesture"), 404
            del data[key]
            _write(data)
        return jsonify(ok=True, actuation=False)
    except (ValueError, OSError):
        return jsonify(ok=False, error="library_unavailable"), 400


def frame():
    try:
        body = request.get_json(silent=True)
        spec = validate(body)
        at = _number(body.get("at", 0), 0, spec["duration"])
        clock = [0.0]
        anim = Animator(clock=lambda: clock[0])
        anim.state.expr = spec["expr"]
        anim.state.mouth.shape = spec["expr"]
        for field, value in spec["initial"].items():
            node, attr = field.split(".")
            setattr(getattr(anim.state, node), attr, value)
        anim.start(spec)
        moments = {0, at}
        for segments in spec["tracks"].values():
            moments.update(s["t1"] for s in segments if s["t1"] < at)
        for moment in sorted(moments):
            clock[0] = moment
            anim.tick()
        anim.state.render_time = at
        png = FaceRenderer(cfg={}, size=240).render_png_bytes(anim.state)
        return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return jsonify(ok=False, error="invalid_frame", actuation=False), 400


def register(app):
    app.add_url_rule("/face-studio", "face_studio_page", page)
    app.add_url_rule("/api/face-studio/gestures", "face_studio_library", library, methods=["GET", "POST"])
    app.add_url_rule("/api/face-studio/gestures/<key>", "face_studio_delete", delete, methods=["DELETE"])
    app.add_url_rule("/api/face-studio/frame", "face_studio_frame", frame, methods=["POST"])
