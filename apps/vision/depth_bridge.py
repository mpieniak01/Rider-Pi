#!/usr/bin/env python3
"""
Vision Depth Estimation Bridge – zasila mapper danymi o przeszkodach.

Subskrybuje stany nawigatora oraz topic `obstacle.map` (fallback: `vision.obstacle`)
 i publikuje uproszczone punkty odległości w `vision.obstacle.data`.
"""

from __future__ import annotations

import os
import time
from typing import Any

from common.bus import (
    TOPIC_NAVIGATOR_STATE,
    TOPIC_OBSTACLE_MAP,
    TOPIC_VISION_OBSTACLE,
    TOPIC_VISION_OBSTACLE_DATA,
    BusPub,
    BusSub,
)

DEFAULT_OBSTACLE_DISTANCE = float(os.getenv("VISION_DEFAULT_OBSTACLE_DISTANCE", "1.5"))
MIN_OBSTACLE_DISTANCE = float(os.getenv("VISION_MIN_OBSTACLE_DISTANCE", "0.3"))
MAX_OBSTACLE_DISTANCE = float(os.getenv("VISION_MAX_OBSTACLE_DISTANCE", "3.0"))


def estimate_distance_from_confidence(confidence: float) -> float:
    if confidence < 0.5:
        return MAX_OBSTACLE_DISTANCE
    norm_conf = (confidence - 0.5) / 0.5
    distance = MAX_OBSTACLE_DISTANCE - (norm_conf * (MAX_OBSTACLE_DISTANCE - MIN_OBSTACLE_DISTANCE))
    return max(MIN_OBSTACLE_DISTANCE, min(MAX_OBSTACLE_DISTANCE, distance))


def convert_obstacle_to_points(obstacle_data: dict[str, Any]) -> list[dict[str, float]]:
    present = obstacle_data.get("present", False)
    confidence = float(obstacle_data.get("confidence") or 0.0)
    if not present or confidence <= 0:
        return []
    distance = estimate_distance_from_confidence(confidence)
    angle = float(obstacle_data.get("angle", 0.0))
    return [{"angle": angle, "distance": distance}]


class DepthBridge:
    """Publikuje vision.obstacle.data na bazie obstacle.map / vision.obstacle."""

    def __init__(self) -> None:
        self.pub = BusPub()
        self.sub = BusSub([TOPIC_NAVIGATOR_STATE, TOPIC_OBSTACLE_MAP, TOPIC_VISION_OBSTACLE])
        self._navigator_active = False

    def run(self) -> None:
        print("[vision_depth] bridge started", flush=True)
        while True:
            topic, payload = self.sub.recv(timeout_ms=500)
            if not topic:
                continue
            if topic == TOPIC_NAVIGATOR_STATE:
                self._handle_navigator_state(payload or {})
            elif topic in (TOPIC_OBSTACLE_MAP, TOPIC_VISION_OBSTACLE):
                self._handle_obstacle(topic, payload or {})

    def _handle_navigator_state(self, data: dict[str, Any]) -> None:
        self._navigator_active = bool(data.get("active"))
        state = data.get("state", "idle")
        print(f"[vision_depth] navigator: active={self._navigator_active}, state={state}", flush=True)

    def _handle_obstacle(self, topic: str, data: dict[str, Any]) -> None:
        if not self._navigator_active:
            return
        payload = {
            "present": bool(data.get("present")),
            "confidence": float(data.get("confidence") or 0.0),
            "ts": data.get("ts", time.time()),
        }
        points = convert_obstacle_to_points(payload)
        out = {
            "obstacles": points,
            "ts": payload["ts"],
            "source": "obstacle.map" if topic == TOPIC_OBSTACLE_MAP else "vision.obstacle",
        }
        self.pub.publish(TOPIC_VISION_OBSTACLE_DATA, out, add_ts=False)
        if points:
            print(
                f"[vision_depth] published {len(points)} obstacle points "
                f"(conf={payload['confidence']:.2f} dist={points[0]['distance']:.2f}m)",
                flush=True,
            )


def main() -> None:
    bridge = DepthBridge()
    bridge.run()


if __name__ == "__main__":
    main()
