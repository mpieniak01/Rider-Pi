"""Admission checks shared by the privileged script and systemctl fallback."""

from __future__ import annotations

import json
import os
from pathlib import Path

from common.service_catalog import UNIT_CATALOG, unit_availability


def _intent(unit: str) -> dict:
    path = Path(os.getenv("FEATURE_STATE_PATH", "/run/rider-motion/feature_state.json"))
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        value = state.get("service_intents", {}).get(unit, {})
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _stop_action(unit, read_status, request_stop):
    from services.core.feature_cleanup import inactive_navigation_target

    if unit in {
        "rider-venom-navigation.service",
        "rider-venom-navigation.target",
        "rider-venom-perception.service",
        "rider-venom-perception.target",
    }:
        observed = read_status()
        if (
            observed.get("state") == "DISARMED"
            and observed.get("owner") is None
            and observed.get("ready") is True
            and observed.get("stale") is False
        ):
            return {"ok": True, "effects": ["already_disarmed_navigation_stop"]}
    if inactive_navigation_target(unit):
        # This target has no process/dependencies; its producer has exited.
        # Stopping it is bookkeeping, not a second global motion STOP that
        # would invalidate the newly admitted operator generation.
        return {"ok": True, "effects": ["empty_navigation_target_stop"]}
    result = request_stop()
    return {**result, "ok": bool(result.get("ok") and result.get("confirmed"))}


def _moving_start_permission(unit, action, meta, read_status):
    safety = read_status()
    capabilities = safety.get("capabilities", {})
    required = ("action",) if unit == "rider-choreographer.service" else ("move", "turn")
    characterized = isinstance(capabilities, dict) and all(
        isinstance(capabilities.get(name), dict)
        and capabilities[name].get("available") is True
        and capabilities[name].get("stop_verified") is True
        for name in required
    )
    intent = _intent(unit)
    permitted = (
        action == "start"
        and safety.get("ready") is True
        and safety.get("can_move") is True
        and safety.get("owner") == meta["motion_owner"]
        and intent.get("generation") == safety.get("generation")
        and isinstance(intent.get("request_id"), str)
        and bool(intent["request_id"])
        and characterized
    )
    return {
        "ok": bool(permitted),
        "error": None if permitted else "operator_motion_permission_required",
        "safety": safety,
    }


def check(unit: str, action: str) -> dict:
    meta = UNIT_CATALOG.get(unit)
    if not meta or action not in {"start", "stop", "restart", "enable", "disable"}:
        return {"ok": False, "error": "unit_or_action_not_catalogued"}
    available = unit_availability(unit)
    if action in {"start", "restart", "enable"} and not available["start_available"]:
        return {"ok": False, "error": available["start_unavailable_reason"], **available}
    if action == "enable" and meta["lifecycle"] != "startup":
        return {"ok": False, "error": "on_demand_autostart_forbidden"}
    if unit == "motion-executor.service" and action == "start":
        # PR01 guarantees read-only SDK construction and a fresh DISARMED gate.
        return {"ok": True, "effects": ["read_only_disarmed_executor_start"]}
    if not meta["can_move"] or action in {"enable", "disable"}:
        return {"ok": True}
    from services.safety_contract import read_status, request_stop

    if action == "stop":
        return _stop_action(unit, read_status, request_stop)
    return _moving_start_permission(unit, action, meta, read_status)
