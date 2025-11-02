#!/usr/bin/env python3
"""
apps/motion/tracking_controller.py
Subscribes to vision/tracking/offset and controls robot rotation to follow objects.
Uses proportional controller with dead zone and timeout.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

import zmq

from drivers.xgo import XgoAdapter

BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
ZMQ_ADDR_SUB = f"tcp://127.0.0.1:{BUS_SUB_PORT}"

# Controller parameters
KP = float(os.getenv("TRACKING_KP", "0.15"))  # Proportional gain
DEAD_ZONE = float(os.getenv("TRACKING_DEAD_ZONE", "0.1"))  # No action if |offset| < this
TIMEOUT_SEC = float(os.getenv("TRACKING_TIMEOUT", "1.0"))  # Stop after this time without updates
MAX_SPEED = float(os.getenv("TRACKING_MAX_SPEED", "0.20"))  # Max rotation speed (0..1)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default


class TrackingController:
    def __init__(self):
        self.xgo = XgoAdapter()
        self.lock = threading.Lock()
        self.last_offset_ts = 0.0
        self.current_mode = "NONE"

        # Enable stabilization
        try:
            imu_on = _env_int("RIDER_IMU", 1)
            self.xgo.set_stabilization(bool(imu_on))
        except Exception:
            pass

    def on_tracking_offset(self, offset_x: float, mode: str) -> None:
        """
        Handle tracking offset message.
        offset_x: -1.0 (left) to +1.0 (right), 0.0 = centered
        """
        now = time.time()

        with self.lock:
            self.last_offset_ts = now
            self.current_mode = mode

            # Apply dead zone
            if abs(offset_x) < DEAD_ZONE:
                rotation_speed = 0.0
            else:
                # Proportional controller
                rotation_speed = KP * offset_x
                # Clamp to max speed
                rotation_speed = max(-MAX_SPEED, min(MAX_SPEED, rotation_speed))

            # Execute rotation
            if rotation_speed != 0.0:
                direction = "right" if rotation_speed > 0 else "left"
                speed = abs(rotation_speed)
                print(f"[tracking] rotate {direction} @ {speed:.3f} (offset={offset_x:.3f})", flush=True)
                self.xgo.spin(direction, speed, duration=0.1, block=False)
            else:
                # In dead zone, stop
                self.xgo.stop()

    def watchdog_loop(self) -> None:
        """Stop robot if no tracking updates received within timeout."""
        while True:
            try:
                now = time.time()
                with self.lock:
                    if self.current_mode != "NONE":
                        time_since_update = now - self.last_offset_ts
                        if time_since_update > TIMEOUT_SEC:
                            print(f"[tracking] timeout ({time_since_update:.1f}s) - stopping", flush=True)
                            self.xgo.stop()
                            self.current_mode = "NONE"

                time.sleep(0.2)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"[tracking] watchdog error: {e}", flush=True)
                time.sleep(0.2)


def zmq_sub(topics: list[str]) -> zmq.Socket:
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.SUB)
    s.connect(ZMQ_ADDR_SUB)
    s.setsockopt(zmq.RCVTIMEO, 100)  # 100ms timeout
    for t in topics:
        s.setsockopt_string(zmq.SUBSCRIBE, t)
    return s


def _json_loads(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        return {}


def sub_recv(sock: zmq.Socket) -> tuple[str, dict[str, Any]]:
    """Receive message from SUB socket."""
    try:
        parts = sock.recv_multipart()
        if not parts:
            return "", {}
        if len(parts) == 1:
            s = parts[0].decode("utf-8", "replace")
            if " " in s:
                topic, payload = s.split(" ", 1)
                return topic, _json_loads(payload)
            return s, {}
        topic = parts[0].decode("utf-8", "replace")
        payload = "".join(p.decode("utf-8", "replace") for p in parts[1:])
        return topic, _json_loads(payload)
    except zmq.Again:
        return "", {}
    except Exception:
        return "", {}


def main():
    print("[tracking_controller] starting", flush=True)
    controller = TrackingController()

    # Start watchdog thread
    threading.Thread(target=controller.watchdog_loop, daemon=True).start()

    # Subscribe to tracking offset topic
    sub = zmq_sub(["vision/tracking/offset"])

    print("[tracking_controller] listening for tracking offset...", flush=True)

    while True:
        try:
            topic, data = sub_recv(sub)
            if not topic:
                continue

            if topic == "vision/tracking/offset":
                offset_x = data.get("offset_x", 0.0)
                mode = data.get("mode", "unknown")
                controller.on_tracking_offset(offset_x, mode)

        except KeyboardInterrupt:
            print("[tracking_controller] stopping", flush=True)
            controller.xgo.stop()
            break
        except Exception as e:
            print(f"[tracking_controller] error: {e}", flush=True)
            time.sleep(0.1)


if __name__ == "__main__":
    main()
