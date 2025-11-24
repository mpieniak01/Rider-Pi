#!/usr/bin/env python3
"""
apps.motion.executor

Przyjmuje komendy ruchu z busa (`cmd.move`, `cmd.stop`, `cmd.motion.*`, `tracking.pose`)
i wykonuje je na XGO z zachowaniem watchdog/deadman.
"""

from __future__ import annotations

import os
import time
from typing import Any

from apps.motion.main import MotionController, _make_adapter, estop_triggered, motion_enabled
from common import bus

DEADMAN_MS = float(os.getenv("MOTION_EXECUTOR_DEADMAN_MS", "600"))
TRACKING_LX = float(os.getenv("MOTION_TRACKING_LX", "0.12"))
TRACKING_AZ_GAIN = float(os.getenv("MOTION_TRACKING_AZ_GAIN", "1.0"))
CMD_TIMEOUT_MS = float(os.getenv("MOTION_CMD_TIMEOUT_MS", "1000"))

SUB_TOPICS = [
    "cmd.move",
    "cmd.stop",
    "cmd.motion.forward",
    "cmd.motion.backward",
    "cmd.motion.left",
    "cmd.motion.right",
    "cmd.motion.turn_left",
    "cmd.motion.turn_right",
    "cmd.motion.stop",
    "tracking.pose",
]


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def as_move_from_tracking(payload: dict[str, Any]) -> tuple[float, float]:
    target = payload.get("target") or {}
    x = float(target.get("x", 0.0) or 0.0)
    az = clamp(x * TRACKING_AZ_GAIN, -1.0, 1.0)
    lx = TRACKING_LX
    return lx, az


def as_move_from_legacy(topic: str, payload: dict[str, Any]) -> tuple[float, float]:
    speed = float(payload.get("speed", 0.3) or 0.3)
    if "forward" in topic:
        return speed, 0.0
    if "backward" in topic:
        return -speed, 0.0
    if "left" in topic:
        return 0.0, 0.5
    if "right" in topic:
        return 0.0, -0.5
    if "turn_left" in topic:
        return 0.0, 1.0
    if "turn_right" in topic:
        return 0.0, -1.0
    return 0.0, 0.0


def main() -> int:
    adapter = _make_adapter()
    controller = MotionController(adapter)
    sub = bus.BusSub(SUB_TOPICS)
    pub = bus.BusPub()

    last_cmd_ts = 0.0
    last_move = (0.0, 0.0)

    while True:
        topic, payload = sub.recv(timeout_ms=50)
        now = time.time()

        if topic is None:
            pass
        elif topic == "cmd.stop" or topic.endswith("cmd.motion.stop"):
            controller.stop()
            pub.publish("motion.bridge.event", {"event": "stop", "ts": now}, add_ts=False)
        elif topic == "cmd.move":
            lx = float(payload.get("vx", 0.0) or 0.0)
            az = float(payload.get("az", payload.get("yaw", 0.0) or 0.0))
            controller.drive(lx, az)
            last_cmd_ts = now
            last_move = (lx, az)
        elif topic.startswith("cmd.motion."):
            lx, az = as_move_from_legacy(topic, payload or {})
            controller.drive(lx, az)
            last_cmd_ts = now
            last_move = (lx, az)
        elif topic == "tracking.pose":
            lx, az = as_move_from_tracking(payload or {})
            controller.drive(lx, az)
            last_cmd_ts = now
            last_move = (lx, az)

        # watchdog/deadman
        if last_cmd_ts and (now - last_cmd_ts) * 1000.0 > DEADMAN_MS:
            controller.stop()
            last_cmd_ts = 0.0
            pub.publish("motion.bridge.event", {"event": "auto_stop", "reason": "deadman"}, add_ts=True)

        # sterowanie rampą + watchdog
        dt = 0.02
        if motion_enabled() and not estop_triggered():
            controller.tick(dt)
        else:
            controller.stop()

        # telemetria stanu ruchu
        pub.publish(
            "motion.state",
            {
                "ts": time.time(),
                "cmd": {"lx": last_move[0], "az": last_move[1]},
                "moving": (abs(last_move[0]) > 0.0 or abs(last_move[1]) > 0.0),
            },
            add_ts=False,
        )
        time.sleep(dt)


if __name__ == "__main__":
    import sys

    sys.exit(main())
