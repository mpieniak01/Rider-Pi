#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable, Iterator

import zmq

# Broker endpoints (możesz nadpisać ENV-em; zostawiamy wartości domyślne)
XPUB_ENDPOINT = os.getenv("BUS_XPUB", "tcp://127.0.0.1:5556")  # SUB łączy się TU
XSUB_ENDPOINT = os.getenv("BUS_XSUB", "tcp://127.0.0.1:5555")  # PUB łączy się TU

# ============================================================================
# Topic constants for robot control
# ============================================================================

# Balance/stabilization control
# Payload: {"enabled": bool, "ts": float}
TOPIC_MOTION_BALANCE = "cmd.balance"

# Height/suspension control
# Payload: {"height": int (0-255), "ts": float}
TOPIC_MOTION_HEIGHT = "cmd.height"

# ============================================================================
# Topic constants for vision tracking (Follow Me feature)
# ============================================================================

# Published offset for tracking target
# Payload: {"offset_x": float, "offset_y": float, "ts": float}
TOPIC_VISION_TRACKING_OFFSET = "vision.tracking.offset"

# Unified tracking mode control
# Payload: {"mode": "face"|"hand"|"none", "ts": float}
TOPIC_TRACKING_MODE_SET = "tracking.mode:set"

# ============================================================================
# Topic constants for navigator (Rekonesans mode - Autonomous exploration)
# ============================================================================

# Navigator state updates (published by navigator)
# Payload: {"active": bool, "state": str, "strategy": str, "obstacle_present": bool, "ts": float}
# States: "idle", "exploring", "avoiding", "stopped", "returning_home", "path_blocked"
TOPIC_NAVIGATOR_STATE = "navigator.state"

# Obstacle detection from vision (binary - obstacle present/absent)
# Payload: {"type": "obstacle", "present": bool, "confidence": float, "edge_pct": float, "ts": float}
TOPIC_VISION_OBSTACLE = "vision.obstacle"

# ============================================================================
# Topic constants for odometry (Stage 2 - Position tracking)
# ============================================================================

# Estimated robot position and orientation (published by odometry module)
# Payload: {"x": float, "y": float, "theta": float, "theta_deg": float, "ts": float}
# Coordinates: x, y in meters; theta in radians (0 = forward at start)
TOPIC_ROBOT_POSE = "robot.pose"

# Raw IMU data from robot sensors (published by motion bridge)
# Payload: {"roll": float, "pitch": float, "yaw": float, "ts": float}
# Angles in degrees; yaw is used by odometry for orientation correction
TOPIC_IMU_DATA = "imu.data"

# Motion commands for robot movement (published by navigator, API, manual control)
# Payload: {"type": "drive"|"stop", "lx": float, "az": float, "ts": float}
# lx: linear velocity (-1.0 to 1.0), az: angular velocity (-1.0 to 1.0)
TOPIC_MOTION_COMMAND = "motion"

# ============================================================================
# Topic constants for mapper (Stage 3 - SLAM mapping)
# ============================================================================

# Obstacle data with distance estimation (published by vision depth bridge)
# Payload: {"obstacles": [{"angle": float, "distance": float}, ...], "ts": float}
# angle in degrees (relative to robot heading), distance in meters
TOPIC_VISION_OBSTACLE_DATA = "vision.obstacle.data"

# Navigator requests occupancy grid map from mapper (published by navigator)
# Payload: {"request_id": float, "ts": float}
TOPIC_NAVIGATOR_MAP_REQUEST = "navigator.map.request"

# Mapper publishes occupancy grid data in response to request
# Payload: {"grid": [[int]], "width_cells": int, "height_cells": int,
#           "resolution_m": float, "origin_x": float, "origin_y": float,
#           "width_m": float, "height_m": float, "ts": float}
# grid values: 0=free, 127=unknown, 255=occupied
TOPIC_MAPPER_MAP_DATA = "mapper.map.data"

# ============================================================================
# Topic constants for return to home (Stage 4 - Path planning)
# ============================================================================

# Start return to home sequence (published by API or navigator control)
# Payload: {"action": "return_home", "ts": float}
TOPIC_NAVIGATOR_RETURN_HOME_START = "navigator.return_home.start"


def now_ts() -> float:
    return time.time()


class BusPub:
    """
    Publisher: łączy się do XSUB brokera i publikuje multipart [topic, json].
    Kompatybilny wstecz z poprzednią wersją (publish(topic, payload)).
    """

    def __init__(self, topic_prefix: str = "", warmup_ms: int = 0):
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.PUB)
        # nie trzymamy długo gniazda przy zamknięciu
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.connect(XSUB_ENDPOINT)
        self.prefix = topic_prefix.rstrip(".")
        # opcjonalny warmup: w niektórych topologiach ZMQ PUB-SUB pomaga 1–10 ms
        if warmup_ms > 0:
            time.sleep(warmup_ms / 1000.0)

    def _full_topic(self, topic: str) -> str:
        return f"{self.prefix}.{topic}" if self.prefix else topic

    def publish(self, topic: str, payload: dict, add_ts: bool = False) -> None:
        """
        Wyślij wiadomość. Jeśli add_ts=True i brak 'ts' w payload, doda znacznik czasu.
        """
        if add_ts and "ts" not in payload:
            payload = dict(payload)
            payload["ts"] = now_ts()
        t = self._full_topic(topic).encode("utf-8")
        msg = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.sock.send_multipart([t, msg])

    # wsteczna kompatybilność: metoda/argumenty jak wcześniej
    def send(self, topic: str, payload: dict) -> None:
        self.publish(topic, payload)

    def close(self) -> None:
        try:
            self.sock.close(0)
        except Exception:
            pass

    # context manager
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class BusSub:
    """
    Subscriber: łączy się do XPUB brokera i nasłuchuje na wybranych tematach.
    Zwraca (topic:str|None, payload:dict|None).
    """

    def __init__(self, topics: str | Iterable[str]):
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.SUB)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.connect(XPUB_ENDPOINT)

        if isinstance(topics, str):
            topics = [topics]
        for t in topics:
            self.subscribe(t)

    def subscribe(self, topic: str) -> None:
        """Dopisz subskrypcję w locie."""
        self.sock.setsockopt(zmq.SUBSCRIBE, topic.encode("utf-8"))

    def recv(self, timeout_ms: int | None = None) -> tuple[str | None, dict | None]:
        """
        Blokujące (z opcjonalnym timeoutem) pobranie jednej wiadomości.
        Toleruje 1-frame (payload only) i 2+ frames (topic, payload[, ...]).
        Zwraca (topic, payload) albo (None, None) przy timeout.
        """
        # timeout (poll)
        if timeout_ms is not None:
            if self.sock.poll(timeout=timeout_ms) <= 0:
                return None, None

        # odbierz ramek (lista bytes)
        frames = self.sock.recv_multipart()
        if not frames:
            return "", None

        # normalizacja: topic = 1. ramka (jeśli >=2), payload = ostatnia
        if len(frames) >= 2:
            topic_b, payload_b = frames[0], frames[-1]
        else:
            topic_b, payload_b = b"", frames[0]

        # decode topic
        try:
            topic = topic_b.decode("utf-8", errors="ignore")
        except Exception:
            topic = ""

        # decode payload -> dict (JSON) lub None
        payload: dict | None = None
        if isinstance(payload_b, (bytes, bytearray)):
            try:
                payload = json.loads(payload_b.decode("utf-8", errors="ignore"))
            except Exception:
                payload = None
        elif isinstance(payload_b, str):
            try:
                payload = json.loads(payload_b)
            except Exception:
                payload = None
        elif isinstance(payload_b, dict):
            payload = payload_b

        return topic, payload

    def recv_iter(self) -> Iterator[tuple[str, dict]]:
        """Nieskończona pętla generatora (użyteczne w wątkach)."""
        while True:
            topic, payload = self.recv()
            if topic is None:
                continue
            if payload is None:
                continue
            yield topic, payload

    # pozwala używać:  for topic, msg in sub:
    def __iter__(self) -> Iterator[tuple[str, dict]]:
        return self.recv_iter()

    def close(self) -> None:
        try:
            self.sock.close(0)
        except Exception:
            pass

    # context manager
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
