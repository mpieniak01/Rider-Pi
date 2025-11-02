#!/usr/bin/env python3
"""
Vision Depth Estimation Bridge for SLAM Mapping

This module monitors the navigator state and when in reconnaissance mode,
publishes obstacle data with estimated distances for the mapper.

Current implementation: Uses simplified distance estimation based on obstacle
detection confidence and image position. This is a placeholder for future
mono-depth estimation using TFLite models.

Topics IN:  navigator.state, vision.obstacle
Topics OUT: vision.obstacle.data
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

import zmq

BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
ZMQ_ADDR_PUB = f"tcp://127.0.0.1:{BUS_PUB_PORT}"
ZMQ_ADDR_SUB = f"tcp://127.0.0.1:{BUS_SUB_PORT}"

# Depth estimation parameters (simplified model)
# TODO: Replace with actual mono-depth estimation model (TFLite)
DEFAULT_OBSTACLE_DISTANCE = float(os.getenv("VISION_DEFAULT_OBSTACLE_DISTANCE", "1.5"))  # meters
MIN_OBSTACLE_DISTANCE = float(os.getenv("VISION_MIN_OBSTACLE_DISTANCE", "0.3"))  # meters
MAX_OBSTACLE_DISTANCE = float(os.getenv("VISION_MAX_OBSTACLE_DISTANCE", "3.0"))  # meters

# Camera field of view (approximate, depends on camera model)
CAMERA_FOV_HORIZONTAL_DEG = float(os.getenv("VISION_CAMERA_FOV_H", "60.0"))  # degrees

PUB: zmq.Socket | None = None
SUB: zmq.Socket | None = None

# State tracking
_navigator_active = False
_last_obstacle_data = None
_state_lock = threading.Lock()


def zmq_pub() -> zmq.Socket:
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.PUB)
    s.connect(ZMQ_ADDR_PUB)
    return s


def zmq_sub(topics: list[str]) -> zmq.Socket:
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.SUB)
    s.connect(ZMQ_ADDR_SUB)
    try:
        s.setsockopt(zmq.RCVTIMEO, 1000)
    except Exception:
        pass
    for t in topics:
        s.setsockopt_string(zmq.SUBSCRIBE, t)
    return s


def pub(topic: str, payload: dict[str, Any]) -> None:
    try:
        assert PUB is not None
        msg = f"{topic} {json.dumps(payload, ensure_ascii=False)}"
        PUB.send_string(msg)
    except Exception as e:
        print(f"[vision_depth] pub err: {e}", flush=True)


def sub_recv() -> tuple[str, dict[str, Any]]:
    """Receive message from SUB socket"""
    assert SUB is not None
    parts = SUB.recv_multipart()
    if not parts:
        return "", {}
    if len(parts) == 1:
        s = parts[0].decode("utf-8", "replace")
        if " " in s:
            topic, payload = s.split(" ", 1)
            try:
                return topic, json.loads(payload)
            except Exception:
                return topic, {}
        return s, {}
    topic = parts[0].decode("utf-8", "replace")
    try:
        payload = "".join(p.decode("utf-8", "replace") for p in parts[1:])
        return topic, json.loads(payload)
    except Exception:
        return topic, {}


def estimate_distance_from_confidence(confidence: float) -> float:
    """
    Simplified distance estimation based on obstacle confidence.

    High confidence (close to 1.0) = closer obstacle
    Low confidence = farther obstacle

    TODO: Replace with actual depth estimation from mono-depth model
    """
    # Inverse relationship: higher confidence = closer
    # Map confidence [0.5, 1.0] to distance [MAX, MIN]
    if confidence < 0.5:
        return MAX_OBSTACLE_DISTANCE

    # Normalize confidence to [0, 1] range
    norm_conf = (confidence - 0.5) / 0.5

    # Inverse mapping to distance
    distance = MAX_OBSTACLE_DISTANCE - (norm_conf * (MAX_OBSTACLE_DISTANCE - MIN_OBSTACLE_DISTANCE))

    return max(MIN_OBSTACLE_DISTANCE, min(MAX_OBSTACLE_DISTANCE, distance))


def convert_obstacle_to_points(obstacle_data: dict[str, Any]) -> list[dict[str, float]]:
    """
    Convert obstacle detection to list of (angle, distance) points.

    Current implementation: Single point at center
    TODO: Use depth map to generate multiple points across obstacle surface
    """
    present = obstacle_data.get("present", False)
    confidence = obstacle_data.get("confidence", 0.0)

    if not present or confidence < 0.5:
        return []

    # Estimate distance (simplified)
    distance = estimate_distance_from_confidence(confidence)

    # Assume obstacle is straight ahead (angle = 0)
    # TODO: Use bbox position to estimate horizontal angle
    # For now, we place it at center
    angle = 0.0  # radians (0 = straight ahead)

    return [{"angle": angle, "distance": distance}]


def handle_navigator_state(data: dict[str, Any]) -> None:
    """Update navigator active state"""
    global _navigator_active
    with _state_lock:
        _navigator_active = data.get("active", False)
        state = data.get("state", "idle")
        print(f"[vision_depth] navigator: active={_navigator_active}, state={state}", flush=True)


def handle_vision_obstacle(data: dict[str, Any]) -> None:
    """Process obstacle detection and publish depth data if navigator is active"""
    global _last_obstacle_data

    with _state_lock:
        active = _navigator_active
        _last_obstacle_data = data

    if not active:
        return  # Only publish depth data when navigator is active

    # Convert obstacle to points with distance
    obstacles = convert_obstacle_to_points(data)

    # Publish on vision.obstacle.data topic
    payload = {
        "obstacles": obstacles,
        "ts": time.time(),
        "source": "simplified_depth",  # Mark as simplified depth estimation
    }

    pub("vision.obstacle.data", payload)

    if obstacles:
        print(
            f"[vision_depth] published {len(obstacles)} obstacle points: "
            f"{obstacles[0]['angle']:.2f}rad, {obstacles[0]['distance']:.2f}m",
            flush=True,
        )


def rx_loop() -> None:
    """Main receive loop"""
    print("[vision_depth] rx_loop started", flush=True)
    while True:
        try:
            topic, data = sub_recv()

            if topic == "navigator.state":
                handle_navigator_state(data)
            elif topic == "vision.obstacle":
                handle_vision_obstacle(data)

        except KeyboardInterrupt:
            break
        except zmq.Again:
            # Timeout - allows responsive shutdown
            pass
        except Exception as e:
            print(f"[vision_depth] err: {e}", flush=True)
            time.sleep(0.02)


if __name__ == "__main__":
    print("[vision_depth] starting (simplified depth estimation mode)", flush=True)
    print("[vision_depth] TODO: Integrate mono-depth TFLite model for accurate distance", flush=True)

    PUB = zmq_pub()
    SUB = zmq_sub(["navigator.state", "vision.obstacle"])

    rx_loop()
