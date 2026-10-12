"""Wspólny kontrakt poleceń i odczyt statusu, bez importowania SDK robota."""

from __future__ import annotations

import math
import time
import uuid
from typing import Any

from common.actuator_parameters import HEIGHT_MAX, HEIGHT_MIN
from common.agent_control import is_agent, verify_command
from common.bus import TOPIC_MOTION_COMMAND, BusPub

TOPIC_COMMAND = TOPIC_MOTION_COMMAND
SAFE_MAX_DURATION = 0.25
OWNERS = frozenset({"manual", "follow_me", "navigation"})
ACTUATORS = frozenset({"move", "turn", "height", "balance", "action"})


def read_status(max_age_s: float = 3.0) -> dict[str, Any]:
    """Zwróć tylko obserwowany stan wykonawcy; brak danych oznacza UNKNOWN."""
    try:
        from apps.safety.state import read_status as read_executor_status

        return read_executor_status(max_age_s=max_age_s)
    except (ImportError, OSError, ValueError, TypeError) as exc:
        return {
            "contract_version": 1,
            "state": "UNKNOWN",
            "ready": False,
            "can_move": False,
            "read_only": True,
            "observed_at": None,
            "owner": None,
            "generation": None,
            "hardware_ready": False,
            "error": f"safety_status_unavailable: {exc}",
            "last_ack": None,
        }


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} must be finite in [{minimum}, {maximum}]")
    return number


def command_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Walidacja identyczna dla HTTP i lokalnych producentów poleceń."""
    if not isinstance(payload, dict):
        raise ValueError("JSON object expected")
    action = str(payload.get("action") or "").lower()
    if action not in ACTUATORS | {"arm", "disarm", "estop", "clear_estop", "stop"}:
        raise ValueError("unknown action")
    command = dict(payload)
    command.update(
        action=action,
        request_id=str(payload.get("request_id") or uuid.uuid4().hex),
        source=str(payload.get("source") or "manual"),
    )
    if is_agent(command) and action in ACTUATORS | {'arm', 'clear_estop'}:
        verify_command(command)
    if action in {"arm", "clear_estop"}:
        if payload.get("operator_consent") is not True:
            raise ValueError("explicit operator consent required")
        if not isinstance(payload.get("operator_plan"), str) or not 1 <= len(payload["operator_plan"].strip()) <= 512:
            raise ValueError("specific operator_plan required")
        if payload.get("owner", "manual") not in OWNERS:
            raise ValueError("invalid owner")
        mode = payload.get("arming_mode", "timed")
        if not isinstance(mode, str) or mode not in {"timed", "operator"}:
            raise ValueError("invalid_arming_mode")
        if mode == "operator":
            if (
                payload.get("execution_context", "panel") != "panel"
                or payload.get("owner", "manual") != "manual"
                or "lease_s" in payload
            ):
                raise ValueError("operator_arming_panel_only")
        else:
            command["lease_s"] = _number(payload.get("lease_s", 10), "lease_s", 0.1, 30)
        command["owner"] = payload.get("owner", "manual")
    if action in ACTUATORS | {"arm", "clear_estop"}:
        generation = payload.get("generation")
        seq = payload.get("seq")
        if not isinstance(generation, str) or not generation:
            raise ValueError("generation required")
        if isinstance(seq, bool) or not isinstance(seq, int) or not 0 <= seq < 2**63:
            raise ValueError("nonnegative integer seq required")
        if payload.get("source") not in OWNERS | {'agent'}:
            raise ValueError("invalid command source")
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ValueError("request_id required")
        command["ts"] = _number(payload.get("ts"), "ts", 0, time.time() + 0.1)
        if type(payload.get("ttl_ms")) is not int:
            raise ValueError("integer ttl_ms required")
        command["ttl_ms"] = payload["ttl_ms"]
        _number(command["ttl_ms"], "ttl_ms", 1, 500)
        if (time.time() - command["ts"]) * 1000 > command["ttl_ms"]:
            raise ValueError("expired command")
        if action in {"move", "turn"}:
            if not isinstance(payload.get("mode", "pulse"), str) or payload.get("mode", "pulse") not in {
                "pulse",
                "hold",
                "release",
            }:
                raise ValueError("unsupported_motion_mode")
            if payload.get("mode", "pulse") != "pulse" and not (
                payload.get("device_settings") is True
                and payload.get("source") == "manual"
                and payload.get("execution_context") == "panel"
            ):
                raise ValueError("hold_operator_panel_only")
            if payload.get("device_settings") is True:
                if payload.get("direction") not in {"forward", "backward", "left", "right"}:
                    raise ValueError("manual_direction")
                if any(key in payload for key in ("vx", "yaw", "duration")):
                    raise ValueError("device_settings_ambiguous_command")
            else:
                command["vx"] = _number(payload.get("vx", 0), "vx", -1, 1)
                command["yaw"] = _number(payload.get("yaw", 0), "yaw", -1, 1)
                command["duration"] = _number(payload.get("duration", 0.1), "duration", 0.01, SAFE_MAX_DURATION)
        elif action == "height":
            height = _number(payload.get("height"), "height", HEIGHT_MIN, HEIGHT_MAX)
            if int(height) != height:
                raise ValueError("height must be integer")
            command["height"] = int(height)
        elif action == "balance" and not isinstance(payload.get("enabled"), bool):
            raise ValueError("enabled must be boolean")
    else:
        command.setdefault("ts", time.time())
        command.setdefault("ttl_ms", 500)
    return command


def _permission(command: dict[str, Any], status: dict[str, Any]) -> str | None:
    if command["action"] not in ACTUATORS:
        return None
    if status.get("contract_version") != 1 or status.get("state") != "ARMED":
        return "motion_not_armed"
    if status.get("ready") is not True or status.get("can_move") is not True:
        return "motion_not_ready"
    agent = is_agent(command)
    if agent and not (
        status.get('owner') == 'manual'
        and status.get('execution_context') == 'panel'
        and status.get('arming_mode') == 'operator'
    ):
        return 'agent_operator_arm_required'
    if status.get("generation") != command["generation"] or (not agent and status.get("owner") != command["source"]):
        return "stale_generation_or_wrong_owner"
    if agent:
        if command.get('agent_epoch') != status.get('agent_epoch'):
            return 'agent_epoch_stale'
        if command.get('seq', -1) <= status.get('agent_last_seq', -1):
            return 'stale_sequence'
        if status.get('agent_manual_active') or status.get('manual_agent_grace_remaining_s', 0) > 0:
            return 'agent_manual_priority'
    settings = status.get("manual_settings") or {}
    if type(command.get("settings_revision")) is not int or command["settings_revision"] != settings.get("revision"):
        return "manual_settings_stale"
    capability = (status.get("capabilities") or {}).get(command["action"], {})
    if capability.get("available") is not True or (
        command["action"] not in {"height", "balance"} and capability.get("stop_verified") is not True
    ):
        return "actuator_unavailable_or_uncharacterized"
    return None


def publish_command(payload: dict[str, Any], timeout_s: float = 0.35) -> dict[str, Any]:
    """Wyślij żądanie; sukces wykonawcy musi pochodzić z dopasowanego ACK."""
    command = command_envelope(payload)
    status = read_status()
    refusal = _permission(command, status)
    if refusal:
        return {"ok": False, "confirmed": False, "error": refusal, "safety": status}
    dispatched_at = time.time()
    try:
        with BusPub(warmup_ms=50) as publisher:
            publisher.publish(TOPIC_COMMAND, command)
            return _await_ack(command, dispatched_at, timeout_s)
    except Exception as exc:
        return {"ok": False, "confirmed": False, "error": f"bus_unavailable: {exc}", "safety": status}


def _await_ack(command: dict, dispatched_at: float, timeout_s: float) -> dict:
    deadline = time.monotonic() + max(0.0, min(timeout_s, 1.0))
    while True:
        status = read_status()
        candidates = [status.get("last_ack") or {}] + list(status.get("recent_acks") or [])
        ack = next(
            (
                item
                for item in candidates
                if item.get("request_id") == command["request_id"]
                and item.get("action") == command["action"]
                and item.get("source") == command["source"]
                and item.get("seq") == command.get("seq")
                and item.get("command_generation") == command.get("generation")
                and isinstance(item.get("observed_at"), (int, float))
                and item["observed_at"] >= dispatched_at
                and item.get("status") in {"executed", "rejected"}
            ),
            None,
        )
        if ack is not None:
            accepted = ack.get("accepted") is True
            return {
                "ok": accepted,
                "confirmed": ack.get("status") == "executed",
                "pending": False,
                "request_id": command["request_id"],
                "ack": ack,
                "safety": status,
                "physical_completion": "unverified",
                "error": None if accepted else ack.get("error") or "executor_rejected",
            }
        if time.monotonic() >= deadline:
            return {
                "ok": False,
                "confirmed": False,
                "pending": True,
                "request_id": command["request_id"],
                "safety": status,
                "physical_completion": "unverified",
                "error": "executor_ack_pending",
            }
        time.sleep(0.01)


def request_stop(owner: str | None = None, timeout_s: float = 0.75) -> dict[str, Any]:
    """Zakończenie zadania wymaga ACK STOP i obserwowanego rozbrojenia."""
    result = publish_command({"action": "stop", "source": owner or "manual"}, timeout_s=timeout_s)
    status = result["safety"]
    result["ok"] = bool(result.get("ok") and result.get("confirmed") and status.get("state") in {"DISARMED", "ESTOP"})
    if not result["ok"] and not result.get("error"):
        result["error"] = "stop_not_confirmed"
    return result
