"""Read-only action projection using the same catalog and ownership as admission."""

from common.service_catalog import UNIT_CATALOG, unit_availability


def _action_reason(unit, action, row, installed, consumers, available, meta, moving_allowed):
    reason = None
    if row.get("stale") is True or row.get("error"):
        reason = "unit_observation_unavailable"
    elif not installed:
        reason = "unit_unavailable"
    elif unit == "rider-api.service" and action in {"stop", "restart", "disable"}:
        reason = "forbidden_on_api"
    elif consumers and action in {"stop", "restart", "disable"}:
        reason = "resource_in_use"
    elif action in {"start", "restart", "enable"} and not available["start_available"]:
        reason = available["start_unavailable_reason"]
    elif action == "enable" and meta["lifecycle"] != "startup":
        reason = "on_demand_autostart_forbidden"
    elif action == "restart" and meta["can_move"]:
        reason = "operator_motion_permission_required"
    elif action == "start" and meta["can_move"] and unit != "motion-executor.service" and not moving_allowed:
        reason = "operator_motion_permission_required"
    return reason


def permissions(unit, row, manager):
    meta = UNIT_CATALOG[unit]
    available = unit_availability(unit)
    consumers = [name for name in manager.unit_consumers(unit) if not name.startswith("admin:")]
    installed = row.get("load", row.get("load_state")) == "loaded" and not row.get("error")
    status_reader = getattr(manager, "safety_status", None)
    safety = (
        status_reader() if meta["can_move"] and unit != "motion-executor.service" and callable(status_reader) else {}
    )
    safety = safety if isinstance(safety, dict) else {}
    capabilities = safety.get("capabilities", {})
    required = ("action",) if unit == "rider-choreographer.service" else ("move", "turn")
    moving_allowed = (
        safety.get("ready") is True
        and safety.get("can_move") is True
        and safety.get("owner") == meta["motion_owner"]
        and isinstance(capabilities, dict)
        and all(
            isinstance(capabilities.get(name), dict)
            and capabilities[name].get("available") is True
            and capabilities[name].get("stop_verified") is True
            for name in required
        )
    )
    result = {}
    for action in ("start", "stop", "restart", "enable", "disable"):
        reason = _action_reason(unit, action, row, installed, consumers, available, meta, moving_allowed)
        result[action] = {"allowed": reason is None, "reason": reason}
    return result
