"""Resource routes share the service/task ownership manager."""

from __future__ import annotations

from flask import jsonify, make_response, request

from . import services_api


def _release_pids(payload):
    pids_raw = payload.get("pids")
    if pids_raw is not None and not isinstance(pids_raw, list):
        return None, (jsonify({"ok": False, "error": "pids must be a list"}), 400)
    pids = []
    for item in pids_raw or []:
        try:
            if isinstance(item, bool) or int(item) <= 0:
                raise ValueError("invalid pid")
            pids.append(int(item))
        except (TypeError, ValueError, OverflowError):
            return None, (jsonify({"ok": False, "error": "invalid pid"}), 400)
    return pids, None


def _stop_resource(name, payload):
    units = payload.get("units")
    if units is not None and (
        not isinstance(units, list) or any(not isinstance(unit, str) or not unit for unit in units)
    ):
        return jsonify({"ok": False, "error": "units must be a list of names"}), 400
    return services_api.resource_stop(name, units)


def api_resource(name: str):
    if request.method == "OPTIONS":
        return make_response("", 204)
    if request.method == "GET":
        if name == "led":
            from .hardware_api import led_status

            return jsonify(led_status(request.args.get("name")))
        return services_api.resource_status(name)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "JSON object required"}), 400
    action = str(payload.get("action") or "").strip().lower()
    if name in {"lcd", "led"} and action in {"on", "off", "blink", "auto"}:
        from .hardware_api import device_action

        return device_action(name, payload)

    if action == "release":
        pids, rejection = _release_pids(payload)
        if rejection is not None:
            return rejection
        return services_api.resource_release(name, pids)

    if action == "stop":
        return _stop_resource(name, payload)

    return jsonify({"ok": False, "error": "unknown action", "action": action}), 400
