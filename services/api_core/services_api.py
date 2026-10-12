#!/usr/bin/env python3
"""Service administration shares the authoritative task ownership lock."""

from __future__ import annotations

import json
import time
from typing import Any

from flask import Response, request

from common import systemd_ctrl
from common.service_catalog import (
    CONTRACT_VERSION,
    DEFAULT_REGISTRY,
    UNIT_ALIASES,
    UNIT_CATALOG,
    task_resources,
    unit_availability,
)
from services.core.service_permissions import permissions

from . import resource_diag

ALLOWED_UNITS = UNIT_ALIASES
ALLOWED_ACTIONS = ("start", "stop", "restart", "enable", "disable")
MUTEX_GROUPS = [{"camera-capture@raw.service", "camera-capture@edge.service", "camera-capture@ssd.service"}]


def _json(payload: Any, status: int = 200) -> Response:
    return Response(json.dumps(payload, ensure_ascii=False), mimetype="application/json", status=status)


def _manager():
    from .features_api import feature_manager

    return feature_manager


def _unit_for(name: str | None) -> str | None:
    key = (name or "").strip().lower()
    return key if key in UNIT_CATALOG else ALLOWED_UNITS.get(key)


def _svc_status(unit: str) -> dict:
    row = systemd_ctrl.status(unit)
    meta = UNIT_CATALOG[unit]
    owner = meta["motion_owner"]
    dependencies = sorted(set(row.get("wants", []) + row.get("requires", [])))
    return {
        **meta,
        **row,
        "actions": list(ALLOWED_ACTIONS),
        **unit_availability(unit),
        "permissions": permissions(unit, row, _manager()),
        "motion_owner": owner,
        "consumers": _manager().unit_consumers(unit),
        "dependencies": dependencies,
        "edges_out": [UNIT_CATALOG[dependency]["id"] for dependency in dependencies if dependency in UNIT_CATALOG],
    }


def _conflicts(unit: str) -> list[str]:
    return sorted({candidate for group in MUTEX_GROUPS if unit in group for candidate in group if candidate != unit})


def _build_sequence(unit: str, action: str) -> list[tuple[str, str]]:
    # Conflicts now deny an action rather than stopping another task implicitly.
    return [(unit, action)]


def _known_resource(name: str) -> bool:
    return name in resource_diag.available_resources() or any(
        name in task_resources(feature) for feature in DEFAULT_REGISTRY.values()
    )


def _run_step(unit: str, action: str) -> dict:
    return systemd_ctrl.run_unit_action(unit, action).as_dict()


def resource_status(name: str) -> Response:
    if not _known_resource(name):
        return _json({"error": "unknown resource", "name": name}, 404)
    from services.core.resource_observation import snapshot as observe_resource

    physical = name in resource_diag.available_resources()
    data = (
        observe_resource(name)
        if physical
        else {
            "resource": name,
            "state": "unknown",
            "free": None,
            "holders": [],
            "paths": [],
            "source": "task-catalog",
            "observed_at": None,
            "error": None,
        }
    )
    if name == "camera":
        from services.core.camera_state import snapshot

        data["activity"] = snapshot(owners=data, consumers=_manager().resource_consumers().get(name, []))
    if name == "lcd":
        from services.core.lcd_state import backlight_status

        data["activity"] = backlight_status()
    return _json(
        {
            **data,
            "contract_version": CONTRACT_VERSION,
            "host": "pi",
            "physical": physical,
            "logical": not physical,
            "diagnostic_available": physical,
            "consumers": _manager().resource_consumers().get(name, []),
        }
    )


def resource_release(name: str, pids: list[int] | None = None) -> Response:
    if not _known_resource(name):
        return _json({"error": "unknown resource", "name": name}, 404)
    if name not in resource_diag.available_resources():
        return _json({"ok": False, "error": "resource_diagnostic_unavailable", "name": name}, 409)
    payload = request.get_json(silent=True) or {}
    data = resource_diag.release(
        name,
        limit_pids=pids or [],
        force=payload.get("force") is True,
        operator_consent=payload.get("operator_consent") is True,
    )
    from services.core.resource_observation import invalidate

    invalidate(name)
    return _json(
        data, 200 if data.get("released") else 202 if data.get("pending") else 503 if data.get("signal_sent") else 409
    )


def resource_stop(name: str, units: list[str] | None = None) -> Response:
    if not _known_resource(name):
        return _json({"error": "unknown resource", "name": name}, 404)
    with _manager().transaction():
        return _resource_stop_locked(name, units)


def _resource_stop_locked(name: str, units: list[str] | None) -> Response:
    if name not in resource_diag.available_resources():
        return _json({"ok": False, "error": "resource_diagnostic_unavailable", "name": name}, 409)
    consumers = _manager().resource_consumers().get(name, [])
    if consumers:
        return _json(
            {"ok": False, "error": "resource_in_use", "consumers": consumers, "hint": "Stop the owning task first."},
            409,
        )
    observed = resource_diag.inspect(name)
    if observed.get("error") or observed.get("state") in {"unknown", "unavailable"}:
        return _json({"ok": False, "error": "ownership_unknown", "resource": observed}, 409)
    services = units or sorted(
        {holder.get("service") for holder in observed.get("holders", []) if holder.get("service")}
    )
    allowed = [unit for unit in services if unit in UNIT_CATALOG and name in UNIT_CATALOG[unit]["resources"]]
    if not allowed or len(allowed) != len(services):
        return _json({"ok": False, "error": "no_stoppable_services", "services": services}, 409)
    results = []
    for unit in allowed:
        result = _manager().service_action(unit, "stop")
        results.append(result)
        if not result.get("ok"):
            break
    ok = len(results) == len(allowed) and all(row.get("ok") for row in results)
    after = resource_diag.inspect(name)
    released = ok and after.get("free") is True and not after.get("error")
    return _json(
        {
            "ok": released,
            "released": released,
            "results": results,
            "after": after,
            "pending": ok and not released,
            "error": after.get("error"),
        },
        200 if released else 202 if ok else 409,
    )


def svc_list() -> Response:
    services = [_svc_status(unit) for unit in sorted(UNIT_CATALOG)]
    return _json(
        {
            "contract_version": CONTRACT_VERSION,
            "catalog_version": CONTRACT_VERSION,
            "host": "pi",
            "source": "pi",
            "observed_at": time.time(),
            "stale": any(row.get("stale") for row in services),
            "services": services,
        }
    )


def svc_status(name: str) -> Response:
    unit = _unit_for(name)
    if not unit:
        return _json({"error": "unknown service", "name": name}, 404)
    return _json({"contract_version": CONTRACT_VERSION, **_svc_status(unit)})


def svc_action(name: str) -> Response:
    unit = _unit_for(name)
    if not unit:
        return _json({"error": "unknown service", "name": name}, 404)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _json({"ok": False, "error": "JSON object required"}, 400)
    action = str(payload.get("action") or "").strip().lower()
    if action not in ALLOWED_ACTIONS:
        return _json({"ok": False, "error": "bad action", "allowed": list(ALLOWED_ACTIONS)}, 400)
    if unit == "rider-api.service" and action in {"stop", "restart", "disable"}:
        return _json({"ok": False, "error": "forbidden_on_api", "unit": unit, "action": action}, 409)
    try:
        result = _manager().service_action(unit, action, control=payload)
    except OSError as exc:
        result = {"ok": False, "error": "orchestration_lock_unavailable", "detail": str(exc), "http_status": 503}
    return _json(
        {"contract_version": CONTRACT_VERSION, **result}, result.get("http_status", 200 if result.get("ok") else 503)
    )
