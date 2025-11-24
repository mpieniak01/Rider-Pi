#!/usr/bin/env python3
from __future__ import annotations

from flask import Response, jsonify, make_response, request

from apps.app_logic_core import FeatureManager

feature_manager: FeatureManager = FeatureManager()


def set_feature_manager(manager: FeatureManager) -> None:
    """Pozwala wstrzyknąć testowy FeatureManager (np. z NullPublisher)."""
    global feature_manager
    feature_manager = manager


def _corsify(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp


def feature_handler(name: str):
    """Endpoint: POST /api/logic/feature/<name> {\"enabled\": bool}"""
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))

    payload = request.get_json(silent=True) or {}
    if "enabled" not in payload:
        return _corsify(jsonify({"ok": False, "error": "enabled_required"})), 400

    enabled = bool(payload.get("enabled"))

    try:
        result = feature_manager.set_feature(name, enabled)
        ok = bool(result.get("ok", False))
        return _corsify(jsonify({"ok": ok, "feature": name, "enabled": enabled, "result": result})), (
            200 if ok else 500
        )
    except ValueError:
        return _corsify(jsonify({"ok": False, "error": "unknown_feature", "feature": name})), 404
    except Exception as e:
        return _corsify(jsonify({"ok": False, "error": f"feature_error:{e}", "feature": name})), 500


def feature_registry_handler():
    """Endpoint: GET /api/logic/features – lista scenariuszy i status usług."""
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    data = feature_manager.describe_features()
    return _corsify(jsonify({"ok": True, "features": data})), 200


def feature_state_handler():
    """Endpoint: GET /api/logic/state – aktywne scenariusze i snapshot."""
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))
    data = feature_manager.state_snapshot()
    return _corsify(jsonify({"ok": True, "state": data})), 200


def feature_summary_handler():
    """Endpoint: GET /api/logic/summary – podsumowanie scenariuszy/targetów."""
    if request.method == "OPTIONS":
        return _corsify(make_response("", 204))

    rows = feature_manager.describe_features()
    active_names: list[str] = []
    partial_names: list[str] = []
    summary_rows: list[dict] = []

    for row in rows:
        services = row.get("services", [])
        total = len(services)
        active_count = sum(1 for svc in services if svc.get("active"))
        status = "active" if row.get("active") else ("partial" if active_count else "inactive")
        if status == "active":
            active_names.append(row["name"])
        elif status == "partial":
            partial_names.append(row["name"])

        summary_rows.append(
            {
                "name": row.get("name"),
                "scenario": row.get("scenario"),
                "title": row.get("title"),
                "description": row.get("description"),
                "active": bool(row.get("active")),
                "status": status,
                "services_total": total,
                "services_active": active_count,
                "ensure_cam": row.get("ensure_cam"),
                "tracking_mode": row.get("tracking_mode"),
                "aliases": row.get("aliases", []),
            }
        )

    payload = {
        "features": summary_rows,
        "active": active_names,
        "partial": partial_names,
        "counts": {
            "total": len(summary_rows),
            "active": len(active_names),
            "partial": len(partial_names),
        },
    }
    return _corsify(jsonify({"ok": True, "summary": payload})), 200


__all__ = [
    "feature_handler",
    "feature_registry_handler",
    "feature_state_handler",
    "feature_summary_handler",
    "set_feature_manager",
    "feature_manager",
]
