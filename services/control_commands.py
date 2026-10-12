"""Normalizacja publicznych aliasów sterowania do jednej bramy wykonawcy."""

from __future__ import annotations

from typing import Any

from common.agent_control import is_agent
from common.motion_commands import normalize_control  # public re-export
from services.safety_contract import publish_command


def submit_control(data: dict[str, Any], *, allow_agent=False, allow_agent_stop=False) -> tuple[dict[str, Any], int]:
    try:
        normalized = normalize_control(data)
        if is_agent(normalized) and not (allow_agent or allow_agent_stop and normalized.get('action') == 'stop'):
            raise ValueError('agent_private_endpoint_required')
        result = publish_command(normalized)
    except (TypeError, ValueError, OverflowError) as exc:
        return {"ok": False, "error": str(exc), "confirmed": False}, 400
    if result.get("pending"):
        return result, 202
    if result.get("ok") and result.get("confirmed"):
        return result, 200
    error = result.get("error") or ""
    return result, 503 if error.startswith("bus_unavailable") else 409
