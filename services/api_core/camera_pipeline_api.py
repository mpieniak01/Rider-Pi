"""Passive RAM media routes and the existing camera-domain lifecycle."""

from __future__ import annotations

import json

from flask import Response, current_app, jsonify, request, stream_with_context

from apps.camera.pipeline_ipc import read_frame
from services.camera_pipeline import CameraPipeline


def _pipeline():
    from services.api_core.features_api import feature_manager

    controller = current_app.extensions.get("rider_camera_pipeline")
    if controller is None or controller.manager is not feature_manager:
        controller = CameraPipeline(feature_manager)
        current_app.extensions["rider_camera_pipeline"] = controller
    return controller


def pipeline():
    try:
        if request.method == "GET":
            response, code = _pipeline().status(), 200
        elif request.content_length is None or not 0 < request.content_length <= 2048:
            response, code = {"ok": False, "error": "camera_pipeline_request_size"}, 400
        else:
            response, code = _pipeline().execute(request.get_json(silent=True))
    except (OSError, ValueError):
        response, code = {"ok": False, "error": "camera_pipeline_unavailable"}, 503
    result = jsonify(response)
    result.headers["Cache-Control"] = "no-store"
    return result, code


def _read(**kwargs):
    try:
        return read_frame(**kwargs)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def frame(view=None):
    view = request.args.get("view", "raw") if view is None else view
    if view not in {"raw", "proc"}:
        return jsonify({"ok": False, "error": "camera_pipeline_view_invalid"}), 400
    item = _read(view=view, timeout_ms=250 if view == "proc" else 0)
    if item is None:
        return jsonify({"ok": False, "error": "camera_pipeline_frame_unavailable"}), 503
    data, metadata = item
    return Response(
        data,
        content_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Rider-Source": json.dumps(metadata, separators=(",", ":")),
            "X-Content-Type-Options": "nosniff",
        },
    )


def stream():
    view = request.args.get("view", "raw")
    if view not in {"raw", "proc"}:
        return jsonify({"ok": False, "error": "camera_pipeline_view_invalid"}), 400
    first = _read(view=view, timeout_ms=250)
    if first is None:
        return jsonify({"ok": False, "error": "camera_pipeline_frame_unavailable"}), 503

    @stream_with_context
    def generate():
        item = first
        while item is not None:
            data, metadata = item
            header = (
                "--rider-frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                + str(len(data))
                + "\r\nX-Rider-Source: "
                + json.dumps(metadata, separators=(",", ":"))
                + "\r\n\r\n"
            ).encode()
            yield header + data + b"\r\n"
            item = _read(after=metadata["frame_id"], view=view, timeout_ms=1000)

    return Response(
        generate(),
        content_type="multipart/x-mixed-replace; boundary=rider-frame",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        },
    )


def register(app):
    app.add_url_rule("/api/resource/camera/pipeline", "camera_pipeline", pipeline, methods=["GET", "POST"])
    app.add_url_rule("/api/resource/camera/frame", "camera_pipeline_frame", frame, methods=["GET"])
    app.add_url_rule("/api/resource/camera/stream.mjpg", "camera_pipeline_stream", stream, methods=["GET"])
