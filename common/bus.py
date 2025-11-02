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

# Topic constants for robot control
TOPIC_MOTION_BALANCE = "cmd.balance"  # Balance/stabilization control
TOPIC_MOTION_HEIGHT = "cmd.height"  # Height/suspension control

# Topic constants for vision tracking (Follow Me feature)
TOPIC_VISION_TRACKING_OFFSET = "vision/tracking/offset"  # Published offset for tracking
TOPIC_VISION_FOLLOW_FACE_SET = "vision/follow/face/set"  # Enable face tracking
TOPIC_VISION_FOLLOW_HAND_SET = "vision/follow/hand/set"  # Enable hand tracking
TOPIC_VISION_FOLLOW_STOP = "vision/follow/stop"  # Disable all tracking


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
    Zwraca (topic:str, payload:dict).
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
        Zwraca (topic, payload) albo (None, None) przy timeout.
        """
        if timeout_ms is not None:
            if self.sock.poll(timeout=timeout_ms) <= 0:
                return None, None
        topic, data = self.sock.recv_multipart()
        try:
            payload = json.loads(data.decode("utf-8"))
        except Exception:
            payload = None
        return topic.decode("utf-8"), payload

    def recv_iter(self) -> Iterator[tuple[str, dict]]:
        """Nieskończona pętla generatora (użyteczne w wątkach)."""
        while True:
            topic, payload = self.recv()
            if topic is None:
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
