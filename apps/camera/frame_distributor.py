#!/usr/bin/env python3
"""
apps.camera.frame_distributor

Buforuje klatki z `camera-capture` i publikuje je jako strumień ZMQ,
aby moduły wizji mogły je współdzielić bez ponownego otwierania kamery.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

import zmq

from apps.camera.frame_metadata import file_identity, read_frame
from common import bus

FRAME_STREAM_TOPIC = os.getenv("FRAME_STREAM_TOPIC", "camera.frame.raw").encode("utf-8")
FRAME_STREAM_BIND = os.getenv("FRAME_STREAM_BIND", "tcp://127.0.0.1:5562")
FRAME_POLL_INTERVAL = float(os.getenv("FRAME_POLL_INTERVAL", "0.01"))  # sekundy
DEFAULT_FRAME_PATH = os.getenv("FRAME_DEFAULT_PATH", "/home/pi/robot/data/last_frame.jpg")
HEARTBEAT_TOPIC = os.getenv("FRAME_HEARTBEAT_TOPIC", "camera.heartbeat")


class FrameDistributor:
    def __init__(self) -> None:
        self.ctx = zmq.Context.instance()
        self.pub = self.ctx.socket(zmq.PUB)
        self.pub.setsockopt(zmq.LINGER, 0)
        self.pub.setsockopt(zmq.SNDHWM, 2)
        self.pub.bind(FRAME_STREAM_BIND)

        self.sub = None
        try:
            self.sub = bus.BusSub(HEARTBEAT_TOPIC)
        except Exception as exc:  # pragma: no cover - brak busa
            print(f"[frame-distributor] warn: cannot subscribe to heartbeat ({exc})", file=sys.stderr)

        self.frame_path = DEFAULT_FRAME_PATH
        self.frame_mode = "raw"
        self.last_mtime = 0.0
        self.last_identity = None
        self.frame_id = 0
        self.running = True

        signal.signal(signal.SIGINT, self._stop)
        signal.signal(signal.SIGTERM, self._stop)

    def _stop(self, *_: Any) -> None:
        self.running = False

    def _drain_heartbeat(self) -> None:
        if self.sub is None:
            return
        for _ in range(32):
            topic, payload = self.sub.recv(timeout_ms=0)
            if topic is None:
                break
            if topic != HEARTBEAT_TOPIC or not payload:
                continue
            raw = payload.get("raw_frame_path")
            use_raw = FRAME_STREAM_TOPIC == b"camera.frame.raw" and isinstance(raw, str) and bool(raw)
            path = raw if use_raw else payload.get("last_frame_path")
            if isinstance(path, str) and path:
                self.frame_path = path
            mode = "raw" if use_raw else payload.get("mode")
            if isinstance(mode, str) and mode:
                self.frame_mode = mode

    def _load_frame_bytes(self, path: str) -> tuple[bytes, dict[str, Any]] | None:
        try:
            loaded = read_frame(Path(path))
            if loaded is None:
                return None
            data, source_metadata = loaded
        except FileNotFoundError:
            return None
        except Exception as exc:
            print(f"[frame-distributor] cannot read frame {path}: {exc}", file=sys.stderr)
            return None

        meta: dict[str, Any] = {
            "path": path,
            "size": len(data),
            "mode": self.frame_mode,
            "ts": time.time(),
            "id": self.frame_id,
            **source_metadata,
        }
        return data, meta

    def close(self) -> None:
        self.running = False
        try:
            if self.sub is not None:
                self.sub.close()
        finally:
            self.pub.close(linger=0)

    def loop(self) -> None:
        print(f"[frame-distributor] bind={FRAME_STREAM_BIND} topic={FRAME_STREAM_TOPIC.decode()}", flush=True)
        while self.running:
            self._drain_heartbeat()
            path = self.frame_path
            if not path:
                time.sleep(FRAME_POLL_INTERVAL)
                continue
            try:
                identity = file_identity(Path(path).stat())
            except Exception:
                time.sleep(FRAME_POLL_INTERVAL)
                continue

            if identity == self.last_identity:
                time.sleep(FRAME_POLL_INTERVAL)
                continue

            self.frame_id += 1
            payload = self._load_frame_bytes(path)
            if payload is None:
                time.sleep(FRAME_POLL_INTERVAL)
                continue
            data, meta = payload
            try:
                self.pub.send_multipart(
                    [
                        FRAME_STREAM_TOPIC,
                        json.dumps(meta, ensure_ascii=False).encode("utf-8"),
                        data,
                    ]
                )
                self.last_mtime = meta['mtime']
                self.last_identity = meta['file_identity']
            except Exception as exc:
                print(f"[frame-distributor] publish error: {exc}", file=sys.stderr)
            time.sleep(FRAME_POLL_INTERVAL)


def main() -> int:
    dist = FrameDistributor()
    try:
        dist.loop()
    finally:
        dist.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
