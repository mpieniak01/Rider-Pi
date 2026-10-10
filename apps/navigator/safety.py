"""Fresh authorization for a specific navigation task, with no hardware I/O."""

from __future__ import annotations

from apps.safety.intent import read_service_intent
from services.safety_contract import command_envelope, read_status


def authorize_request(payload):
    envelope = command_envelope(dict(payload, action="move", vx=0, yaw=0, duration=0.01))
    safety = read_status()
    if safety.get("contract_version") != 1 or safety.get("can_move") is not True or safety.get("owner") != "navigation":
        raise ValueError("navigation_not_authorized")
    if envelope["generation"] != safety.get("generation"):
        raise ValueError("stale_navigation_generation")
    if envelope["seq"] <= safety.get("last_seq", -1):
        raise ValueError("stale_navigation_sequence")
    if not read_service_intent("rider-navigator.service", envelope["generation"]):
        raise ValueError("explicit_navigation_task_required")
    return envelope, safety
