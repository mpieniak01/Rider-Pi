"""Capture warm stop authority before waiting for service orchestration."""

from __future__ import annotations


def stop_override(manager, name, enabled):
    if enabled or name != "s14_venom_navigation":
        return None
    safety = manager.safety_status()
    control = safety.get("operator_control") or {}
    if control.get("version") != 1:
        return None
    if (
        control.get("state") == "idle"
        and manager.producer_status("rider-venom-navigation.service").get("operator_control_version") != 1
    ):
        return None
    captured = {key: safety.get(key) for key in ("generation", "state", "owner")}
    operation = (safety.get("operator_control") or {}).get("operation_id")

    def revoke(_owner):
        current = manager.safety_status()
        if (
            captured["owner"] != "navigation"
            or any(current.get(key) != value for key, value in captured.items())
            or (current.get("operator_control") or {}).get("operation_id") != operation
        ):
            # Cleanup of an obsolete producer has no authority over a newer ARM.
            return {"ok": True, "confirmed": True, "superseded": True, "permission_revoked": True}
        return manager.safety_scoped_stop("navigation", captured["generation"])

    return revoke
