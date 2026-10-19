"""Pure command aliases. Never create permission or refresh an old envelope."""

from __future__ import annotations

CANONICAL_TOPIC = "motion.command"
MOTION_TOPIC_PREFIX = "cmd.motion."
INVALID_DIRECTION = "invalid direction"
MOVE_DIRECTIONS = frozenset({"forward", "backward", "left", "right"})
STOP_TOPICS = frozenset({"cmd.stop", "cmd.motion.stop"})
LEGACY_TOPICS = frozenset({"cmd.move", "cmd.balance", "cmd.height", "motion.cmd", "motion"})
DIRECTIONS = {
    "fwd": "forward",
    "up": "forward",
    "back": "backward",
    "down": "backward",
    "turn_left": "left",
    "turn_right": "right",
}


def _direction_vector(data, direction):
    speed = data.get("v", data.get("speed", 0.1))
    vx = data.get("vx", data.get("lx", 0))
    yaw = data.get("yaw", data.get("az", data.get("w", 0)))
    if direction and direction not in MOVE_DIRECTIONS:
        raise ValueError(INVALID_DIRECTION)
    if direction and not any(key in data for key in ("vx", "lx", "yaw", "az", "w")):
        speed = data.get("w", speed) if direction in {"left", "right"} else speed
        if isinstance(speed, bool):
            raise ValueError("speed must be numeric")
        speed = abs(float(speed))
        vx = {"forward": speed, "backward": -speed}.get(direction, 0)
        yaw = {"left": -speed, "right": speed}.get(direction, 0)
    return vx, yaw


def _motion_values(data, action, direction):
    if data.get("device_settings") is True:
        if direction not in MOVE_DIRECTIONS:
            raise ValueError(INVALID_DIRECTION)
        if any(key in data for key in ("vx", "lx", "yaw", "az", "w", "v", "speed", "duration", "dur", "t", "ms")):
            raise ValueError("device_settings_ambiguous_command")
        return {"action": action, "direction": direction}
    vx, yaw = _direction_vector(data, direction)
    duration = data.get("duration", data.get("dur", data.get("t", 0.1)))
    if "ms" in data:
        if isinstance(data["ms"], bool):
            raise ValueError("ms must be numeric")
        duration = float(data["ms"]) / 1000
    return {"vx": vx, "yaw": yaw, "duration": duration}


def normalize_control(data):
    if not isinstance(data, dict):
        raise ValueError("JSON object expected")
    command = dict(data)
    action = str(data.get("action") or data.get("cmd") or data.get("type") or "").lower()
    direction = str(data.get("dir") or data.get("direction") or "").lower()
    direction = DIRECTIONS.get(direction, direction)
    if action in {"forward", "fwd", "up", "back", "backward", "down", "left", "right", "turn_left", "turn_right"}:
        direction, action = DIRECTIONS.get(action, action), "move"
    if not action and direction:
        action = "move"
    if action == "halt":
        action = "stop"
    if action in {"drive", "spin"}:
        action = "move"
    if action in {"move", "turn"}:
        command.update(_motion_values(data, action, direction))
    command["action"] = action
    # Source/generation/seq/request_id/ts/TTL remain exactly as supplied.
    return command


def canonical_command(topic, payload):
    if not isinstance(payload, dict):
        raise ValueError("JSON object expected")
    command = dict(payload)
    if topic in STOP_TOPICS:
        command["action"] = "stop"
    elif topic == "cmd.move":
        command.setdefault("action", "move")
    elif topic in {"cmd.balance", "cmd.height"}:
        command.setdefault("action", topic.split(".")[-1])
    elif topic.startswith(MOTION_TOPIC_PREFIX):
        command.setdefault("action", topic[len(MOTION_TOPIC_PREFIX) :])
    return normalize_control(command)


def protected_topic(topic):
    return topic in LEGACY_TOPICS | STOP_TOPICS | {
        CANONICAL_TOPIC,
        "calibration.activate",
        "odometry.reference",
    } or topic.startswith(MOTION_TOPIC_PREFIX)
