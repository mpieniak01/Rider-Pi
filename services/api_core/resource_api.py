"""Resource routes share the service/task ownership manager."""

from __future__ import annotations

from flask import jsonify, make_response, request

from . import services_api


def api_resource(name: str):
    if request.method == "OPTIONS":
        return make_response("", 204)
    if request.method == "GET":
        return services_api.resource_status(name)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "JSON object required"}), 400
    action = str(payload.get("action") or "").strip().lower()

    if action == "release":
        pids_raw = payload.get("pids")
        if pids_raw is not None and not isinstance(pids_raw, list):
            return jsonify({"ok": False, "error": "pids must be a list"}), 400
        pids = []
        for item in pids_raw or []:
            try:
                if isinstance(item, bool) or int(item) <= 0:
                    raise ValueError("invalid pid")
                pids.append(int(item))
            except (TypeError, ValueError, OverflowError):
                return jsonify({"ok": False, "error": "invalid pid"}), 400
        return services_api.resource_release(name, pids)

    if action == "stop":
        units = payload.get("units")
        if units is not None and (
            not isinstance(units, list) or any(not isinstance(unit, str) or not unit for unit in units)
        ):
            return jsonify({"ok": False, "error": "units must be a list of names"}), 400
        return services_api.resource_stop(name, units)

    return jsonify({"ok": False, "error": "unknown action", "action": action}), 400
