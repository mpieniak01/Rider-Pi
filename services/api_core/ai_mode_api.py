"""API endpoints for AI mode control.

Provides REST API endpoints for:
- GET /api/system/ai-mode - Query current AI processing mode
- PUT /api/system/ai-mode - Change AI processing mode
"""

from __future__ import annotations

from flask import Response, jsonify, make_response, request

from common import ai_mode


def _corsify(resp: Response) -> Response:
    """Add CORS headers to response."""
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, PUT, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def get_ai_mode() -> tuple[Response, int]:
    """GET /api/system/ai-mode - Return current AI processing mode.

    Returns:
        JSON response with mode and timestamp:
        {
            "mode": "local" | "pc_offload",
            "changed_ts": <timestamp>
        }
    """
    info = ai_mode.get_mode_info()
    return _corsify(jsonify(info)), 200


def set_ai_mode() -> tuple[Response, int]:
    """PUT /api/system/ai-mode - Change AI processing mode.

    Expected JSON payload:
        {"mode": "local" | "pc_offload"}

    Returns:
        JSON response:
        {
            "mode": <new_mode>,
            "changed": <bool>,
            "changed_ts": <timestamp>
        }
    """
    # Handle OPTIONS for CORS preflight
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204)), 204

    payload = request.get_json(force=True, silent=True) or {}
    new_mode = payload.get("mode")

    if not new_mode:
        return _corsify(jsonify({"error": "Missing 'mode' parameter"})), 400

    if new_mode not in ("local", "pc_offload"):
        return _corsify(jsonify({"error": "Invalid mode. Must be 'local' or 'pc_offload'"})), 400

    try:
        changed = ai_mode.set_mode(new_mode)
        info = ai_mode.get_mode_info()

        # Publish ZMQ event about mode change
        _publish_mode_changed_event(new_mode, info["changed_ts"])

        result = {
            "mode": info["mode"],
            "changed": changed,
            "changed_ts": info["changed_ts"],
        }
        return _corsify(jsonify(result)), 200

    except ValueError as e:
        return _corsify(jsonify({"error": str(e)})), 400


def _publish_mode_changed_event(mode: str, ts: float) -> None:
    """Publish system.ai.mode.changed event to ZMQ bus.

    Args:
        mode: New AI mode
        ts: Timestamp of the change
    """
    try:
        from common.bus import TOPIC_SYSTEM_AI_MODE_CHANGED, BusPub

        pub = BusPub()
        payload = {
            "mode": mode,
            "ts": ts,
        }
        pub.send(TOPIC_SYSTEM_AI_MODE_CHANGED, payload)
        pub.close()
    except Exception:
        # Don't fail API call if event publishing fails
        # This could happen if ZMQ bus is not available
        pass


def ai_mode_handler() -> tuple[Response, int]:
    """Route handler for /api/system/ai-mode endpoint.

    Dispatches to GET or PUT handler based on request method.
    """
    if request.method == "GET":
        return get_ai_mode()
    elif request.method in ("PUT", "POST"):
        return set_ai_mode()
    elif request.method == "OPTIONS":
        return _corsify(make_response("", 204)), 204
    else:
        return _corsify(jsonify({"error": "Method not allowed"})), 405
