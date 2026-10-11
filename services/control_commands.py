"""Normalizacja publicznych aliasów sterowania do jednej bramy wykonawcy."""

from __future__ import annotations

from typing import Any

from common.motion_commands import normalize_control  # public re-export
from services.safety_contract import publish_command


def submit_control(data: dict[str, Any]) -> tuple[dict[str, Any], int]:
    try:
        result = publish_command(normalize_control(data))
    except (TypeError, ValueError, OverflowError) as exc:
        return {"ok": False, "error": str(exc), "confirmed": False}, 400
    if result.get("pending"):
        return result, 202
    if result.get("ok") and result.get("confirmed"):
        return result, 200
    error = result.get("error") or ""
    return result, 503 if error.startswith("bus_unavailable") else 409
