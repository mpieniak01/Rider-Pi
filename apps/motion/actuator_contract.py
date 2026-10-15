"""Actuator payload validation; no hardware access."""

from apps.motion import manual_settings
from apps.safety.gate import MAX_DURATION_S, finite_number
from common.actuator_parameters import valid_height

SUB_TOPICS = [
    "calibration.activate",
    "motion.command",
    "cmd.move",
    "cmd.stop",
    "cmd.balance",
    "cmd.height",
    "cmd.motion.",
    "motion.cmd",
    "motion",
]
COMMAND_TOPICS = frozenset(SUB_TOPICS) | {
    "cmd.motion.forward",
    "cmd.motion.backward",
    "cmd.motion.left",
    "cmd.motion.right",
    "cmd.motion.turn_left",
    "cmd.motion.turn_right",
    "cmd.motion.stop",
}


def validate_actuator(command: dict) -> dict:
    action = command.get("action")
    if not isinstance(action, str):
        raise ValueError("unknown_action")
    values = {}
    if action in {"move", "turn"}:
        vx = finite_number(command.get("vx", 0.0), "invalid_vx")
        yaw = finite_number(command.get("yaw", command.get("az", 0.0)), "invalid_yaw")
        duration = finite_number(command.get("duration"), "duration_required")
        panel_pulse = (
            command.get("device_settings") is True
            and command.get("direction") in manual_settings.DIRECTIONS
            and (command.get("execution_context"), command.get("source")) in {('panel', 'manual'), ('agent', 'agent')}
        )
        duration_limit = manual_settings.MAX_PANEL_DURATION_S if panel_pulse else MAX_DURATION_S
        if abs(vx) > 1 or abs(yaw) > 1 or not 0 < duration <= duration_limit:
            raise ValueError("motion_limits_exceeded")
        values = {"vx": vx, "yaw": yaw, "duration": duration}
    elif action in {"balance", "stabilization"}:
        if not isinstance(command.get("enabled"), bool):
            raise ValueError("enabled_boolean_required")
        values = {"enabled": command["enabled"]}
    elif action == "height":
        height = command.get("height")
        if not valid_height(height):
            raise ValueError("height_integer_75_115_required")
        values = {"height": height}
    elif action == "action":
        name = command.get("name")
        if name is None:
            action_id = command.get("action_id")
            if not isinstance(action_id, int) or isinstance(action_id, bool):
                raise ValueError("unsupported_action")
            name = {255: "default", 1: "sway", 2: "vertical", 5: "lift_rotate", 6: "circular"}.get(action_id)
        if not isinstance(name, str) or name not in {"default", "sway", "vertical", "lift_rotate", "circular"}:
            raise ValueError("unsupported_action")
        values = {"name": name}
    return values


def decision_duration(command: dict, duration: float, now: float) -> float:
    """Remote decisions expire across local BUS/ACK delays, on the same Pi clock."""
    deadline = command.get("decision_deadline_monotonic")
    if deadline is None:
        return duration
    deadline = finite_number(deadline, "decision_deadline_invalid")
    if command.get("source") != "navigation" or command.get("execution_context") != "panel":
        raise ValueError("decision_deadline_source_invalid")
    remaining = deadline - now
    if not 0.01 <= remaining <= 0.5:
        raise ValueError("decision_deadline_expired")
    return min(duration, remaining)


def decision_feedback_deadline(command: dict, now: float, *, timed_navigation: bool):
    deadline = command.get("decision_feedback_deadline_monotonic")
    if deadline is None:
        return None
    deadline = finite_number(deadline, "decision_feedback_deadline_invalid")
    decision = command.get("decision_deadline_monotonic")
    if (
        not timed_navigation
        or command.get("source") != "navigation"
        or command.get("execution_context") != "panel"
        or decision is None
    ):
        raise ValueError("decision_feedback_source_invalid")
    decision = finite_number(decision, "decision_deadline_invalid")
    if deadline < decision or not 0 < deadline - now <= 0.5:
        raise ValueError("decision_feedback_deadline_expired")
    return deadline
