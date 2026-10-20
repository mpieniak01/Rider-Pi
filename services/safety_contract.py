"""Wspólny kontrakt poleceń i odczyt statusu, bez importowania SDK robota."""

from __future__ import annotations

import math
import time
import uuid
from typing import Any

from apps.safety.journey import validate_arm as validate_journey_arm
from apps.safety.manual_intervention import validate as validate_intervention
from apps.safety.operator_control import ACTIONS as OPERATOR_ACTIONS
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
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite in [{minimum}, {maximum}]") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} must be finite in [{minimum}, {maximum}]")
    return number


def _validate_stop_generation(payload, action):
    """Keep optional generation-bound STOP rejection separate from ordinary command freshness."""
    if action in {"stop", "disarm"} and "expected_generation" in payload:
        expected = payload["expected_generation"]
        if not isinstance(expected, str) or not expected or len(expected) > 128:
            raise ValueError("stale_stop_generation")


def _validate_arming(payload, command):
    """Validate explicit consent and lease mode before ordinary command metadata, preserving error priority."""
    if payload.get("operator_consent") is not True:
        raise ValueError("explicit operator consent required")
    if not isinstance(payload.get("operator_plan"), str) or not 1 <= len(payload["operator_plan"].strip()) <= 512:
        raise ValueError("specific operator_plan required")
    owner = payload.get("owner", "manual")
    if not isinstance(owner, str) or owner not in OWNERS:
        raise ValueError("invalid owner")
    mode = payload.get("arming_mode", "timed")
    if not isinstance(mode, str) or mode not in {"timed", "operator", "journey"}:
        raise ValueError("invalid_arming_mode")
    validate_journey_arm(payload, owner, payload.get("execution_context", "panel"))
    if mode == "operator":
        if payload.get("execution_context", "panel") != "panel" or owner != "manual" or "lease_s" in payload:
            raise ValueError("operator_arming_panel_only")
    elif mode == "timed":
        command["lease_s"] = _number(payload.get("lease_s", 10), "lease_s", 0.1, 30)
    command["owner"] = owner


def _validate_panel_identifier(payload):
    """Reject malformed panel identity without granting or transferring authority."""
    panel = payload["panel_id"]
    if not isinstance(panel, str) or not panel.strip() or len(panel) > 128:
        raise ValueError("invalid_panel_id")


def _validate_metadata(payload, command):
    """Validate command identity, sequence and freshness before actuator values."""
    generation = payload.get("generation")
    seq = payload.get("seq")
    if not isinstance(generation, str) or not generation:
        raise ValueError("generation required")
    if isinstance(seq, bool) or not isinstance(seq, int) or not 0 <= seq < 2**63:
        raise ValueError("nonnegative integer seq required")
    source = payload.get("source")
    if not isinstance(source, str) or source not in OWNERS | {"agent"}:
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


def _validate_device_direction(payload):
    """Device-owned motion settings accept one direction and no competing actuator values."""
    direction = payload.get("direction")
    if not isinstance(direction, str) or direction not in {"forward", "backward", "left", "right"}:
        raise ValueError("manual_direction")
    if any(key in payload for key in ("vx", "yaw", "duration")):
        raise ValueError("device_settings_ambiguous_command")


def _validate_motion(payload, command):
    """Keep held panel motion distinct from bounded numeric pulses."""
    mode = payload.get("mode", "pulse")
    if not isinstance(mode, str) or mode not in {"pulse", "hold", "release"}:
        raise ValueError("unsupported_motion_mode")
    if mode != "pulse" and not (
        payload.get("device_settings") is True
        and payload.get("source") == "manual"
        and payload.get("execution_context") == "panel"
    ):
        raise ValueError("hold_operator_panel_only")
    if payload.get("device_settings") is True:
        _validate_device_direction(payload)
    else:
        command["vx"] = _number(payload.get("vx", 0), "vx", -1, 1)
        command["yaw"] = _number(payload.get("yaw", 0), "yaw", -1, 1)
        command["duration"] = _number(payload.get("duration", 0.1), "duration", 0.01, SAFE_MAX_DURATION)


def _validate_actuator(payload, command, action):
    """Retain per-actuator parameter checks after the shared metadata boundary."""
    if action in {"move", "turn"}:
        _validate_motion(payload, command)
    elif action == "height":
        height = _number(payload.get("height"), "height", HEIGHT_MIN, HEIGHT_MAX)
        if int(height) != height:
            raise ValueError("height must be integer")
        command["height"] = int(height)
    elif action == "balance" and not isinstance(payload.get("enabled"), bool):
        raise ValueError("enabled must be boolean")


def command_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate HTTP/local commands in the same ordered, side-effect-free stages."""
    if not isinstance(payload, dict):
        raise ValueError("JSON object expected")
    action = str(payload.get("action") or "").lower()
    if action not in ACTUATORS | {"arm", "disarm", "estop", "clear_estop", "stop"} | OPERATOR_ACTIONS:
        raise ValueError("unknown action")
    _validate_stop_generation(payload, action)
    validate_intervention(payload)
    command = dict(payload)
    command.update(
        action=action,
        request_id=str(payload.get("request_id") or uuid.uuid4().hex),
        source=str(payload.get("source") or "manual"),
    )
    if is_agent(command) and action in ACTUATORS | {"arm", "clear_estop"}:
        verify_command(command)
    if action in {"arm", "clear_estop"}:
        _validate_arming(payload, command)
    if action in ACTUATORS | {"arm"} | OPERATOR_ACTIONS and "panel_id" in payload:
        _validate_panel_identifier(payload)
    if action in ACTUATORS | {"arm", "clear_estop"} | OPERATOR_ACTIONS:
        _validate_metadata(payload, command)
        _validate_actuator(payload, command, action)
    else:
        command.setdefault("ts", time.time())
        command.setdefault("ttl_ms", 500)
    return command


def publish_command(payload: dict[str, Any], timeout_s: float = 0.35, *, publisher=None) -> dict[str, Any]:
    """Wyślij żądanie; sukces wykonawcy musi pochodzić z dopasowanego ACK."""
    command = command_envelope(payload)
    status = read_status()
    dispatched_at = time.time()
    try:
        if publisher is not None:
            publisher.publish(TOPIC_COMMAND, command)
            return _await_ack(command, dispatched_at, timeout_s)
        with BusPub(warmup_ms=50) as transient:
            transient.publish(TOPIC_COMMAND, command)
            return _await_ack(command, dispatched_at, timeout_s)
    except Exception as exc:
        return {"ok": False, "confirmed": False, "error": f"bus_unavailable: {exc}", "safety": status}


def _matching_ack(item, command, dispatched_at):
    """Only consistent terminal evidence for this exact command can confirm it."""
    if not isinstance(item, dict):
        return False
    identity = ("request_id", "action", "source")
    if any(item.get(key) != command[key] for key in identity):
        return False
    if item.get("command_generation") != command.get("generation"):
        return False
    sequence = command.get("seq")
    if item.get("seq") != sequence or type(item.get("seq")) is not type(sequence):
        return False
    observed = item.get("observed_at")
    try:
        if type(observed) not in (int, float) or not math.isfinite(observed) or observed < dispatched_at:
            return False
    except OverflowError:
        return False
    if item.get("status") == "executed":
        return item.get("accepted") is True
    return item.get("status") == "rejected" and item.get("accepted") is not True


def _await_ack(command: dict, dispatched_at: float, timeout_s: float) -> dict:
    deadline = time.monotonic() + max(0.0, min(timeout_s, 1.0))
    while True:
        status = read_status()
        candidates = [status.get("last_ack") or {}] + list(status.get("recent_acks") or [])
        ack = next((item for item in candidates if _matching_ack(item, command, dispatched_at)), None)
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


def request_stop(
    owner: str | None = None, timeout_s: float = 0.75, *, expected_generation: str | None = None
) -> dict[str, Any]:
    """Zakończenie zadania wymaga ACK STOP i obserwowanego rozbrojenia."""
    command = {"action": "stop", "source": owner or "manual"}
    if expected_generation is not None:
        command["expected_generation"] = expected_generation
    result = publish_command(command, timeout_s=timeout_s)
    status = result["safety"]
    result["ok"] = bool(result.get("ok") and result.get("confirmed") and status.get("state") in {"DISARMED", "ESTOP"})
    if not result["ok"] and not result.get("error"):
        result["error"] = "stop_not_confirmed"
    return result
