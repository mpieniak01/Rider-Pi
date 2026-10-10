"""Normalizacja publicznych aliasów sterowania do jednej bramy wykonawcy."""

from __future__ import annotations

from typing import Any

from services.safety_contract import publish_command


def normalize_control(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("JSON object expected")
    command = dict(data)
    action = str(data.get("action") or data.get("cmd") or data.get("type") or "").lower()
    direction = str(data.get("dir") or data.get("direction") or "").lower()
    if action in {"forward", "fwd", "up", "back", "backward", "down", "left", "right"}:
        direction, action = action, "move"
    if not action and direction:
        action = "move"
    if action == "halt":
        action = "stop"
    if action in {"drive", "spin", "turn"}:
        direction = direction if action != "drive" else ""
        action = "move"
    if action == "move":
        speed = float(data.get("v", data.get("speed", 0.1)))
        vx = data.get("vx", data.get("lx", 0))
        yaw = data.get("yaw", data.get("az", 0))
        if direction in {"forward", "fwd", "up"}:
            vx, yaw = abs(speed), 0
        elif direction in {"back", "backward", "down"}:
            vx, yaw = -abs(speed), 0
        elif direction == "left":
            vx, yaw = 0, -abs(speed)
        elif direction == "right":
            vx, yaw = 0, abs(speed)
        elif direction:
            raise ValueError("invalid direction")
        duration = data.get("duration", data.get("dur", data.get("t", 0.1)))
        if "ms" in data:
            duration = float(data["ms"]) / 1000
        command.update(vx=vx, yaw=yaw, duration=duration)
    command.update(action=action, source=data.get("source") or "manual")
    return command


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
