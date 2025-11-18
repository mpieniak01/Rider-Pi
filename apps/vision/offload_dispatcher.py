"""Vision offload dispatcher - streams camera frames to Rider-PC."""

from __future__ import annotations

import base64
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from common.bus import (
    TOPIC_PROVIDER_VISION_STATE,
    TOPIC_VISION_FRAME_OFFLOAD,
    TOPIC_VISION_OBSTACLE,
    TOPIC_VISION_OBSTACLE_ENHANCED,
    BusPub,
    BusSub,
)
from common.provider_state import is_pc_mode

LOG = logging.getLogger("vision.offload")
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LAST_FRAME_PATH = DATA_DIR / "last_frame.jpg"
SNAP_DIR = Path(os.getenv("SNAP_DIR") or os.getenv("SNAP_BASE") or REPO_ROOT / "snapshots")
SNAP_DIR.mkdir(parents=True, exist_ok=True)
RAW_PATH = Path(os.getenv("RAW_PATH") or SNAP_DIR / "raw.jpg")
RAW_PATH.parent.mkdir(parents=True, exist_ok=True)


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class VisionOffloadDispatcher:
    """Capture frames and send them to PC when provider vision=pc."""

    source: str = field(default_factory=lambda: os.getenv("VISION_OFFLOAD_SOURCE", "file"))
    width: int = int(os.getenv("VISION_OFFLOAD_WIDTH", "320"))
    height: int = int(os.getenv("VISION_OFFLOAD_HEIGHT", "240"))
    fps: float = float(os.getenv("VISION_OFFLOAD_FPS", "5"))
    topic_out: str = TOPIC_VISION_FRAME_OFFLOAD
    frame_source: str = field(default_factory=lambda: os.getenv("VISION_OFFLOAD_SOURCE", "file"))
    frame_file: Path = field(
        default_factory=lambda: Path(
            os.getenv("VISION_OFFLOAD_FRAME_FILE")
            or os.getenv("RAW_PATH")
            or os.path.join(REPO_ROOT, "snapshots", "raw.jpg")
        )
    )
    running: bool = field(default=False, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _pub: BusPub | None = field(default=None, init=False)
    _cap: cv2.VideoCapture | None = field(default=None, init=False)
    _use_camera: bool = field(default=True, init=False)
    _last_file_mtime: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        mode = (self.frame_source or "camera").strip().lower()
        if mode in {"file", "raw", "last_frame", "", "none"}:
            self._use_camera = False
            if mode == "last_frame":
                self.frame_file = LAST_FRAME_PATH
        else:
            self._use_camera = True
        self.frame_file = Path(self.frame_file)
        if not self.frame_file.exists():
            try:
                self.frame_file.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self.running = True
        self._pub = BusPub()
        if self._use_camera:
            cam_source: int | str
            try:
                cam_source = int(self.source)
            except ValueError:
                cam_source = self.source
            self._cap = cv2.VideoCapture(cam_source)
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self._cap.set(cv2.CAP_PROP_FPS, self.fps)
        self._thread = threading.Thread(target=self._loop, name="vision-offload", daemon=True)
        self._thread.start()
        LOG.info(
            "Vision offload dispatcher started (source=%s, %sx%s, fps=%.1f)",
            self.source if self._use_camera else f"file:{self.frame_file}",
            self.width,
            self.height,
            self.fps,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self._thread = None
        self.running = False
        if self._cap:
            self._cap.release()
            self._cap = None
        if self._pub:
            try:
                self._pub.close()
            except Exception:
                pass
            self._pub = None
        LOG.info("Vision offload dispatcher stopped")

    def _loop(self) -> None:
        if not self._pub:
            LOG.error("Vision offload dispatcher missing publisher")
            return
        if self._use_camera and not self._cap:
            LOG.error("Vision offload dispatcher missing capture device")
            return
        interval = 1.0 / max(0.5, self.fps)
        provider_state_sub = BusSub(TOPIC_PROVIDER_VISION_STATE)
        try:
            while not self._stop.is_set():
                if not is_pc_mode("vision"):
                    provider_state_sub.recv(timeout_ms=500)
                    time.sleep(0.5)
                    continue
                frame_bytes: bytes | None = None
                frame = None
                if self._use_camera:
                    ret, cam_frame = self._cap.read()
                    if not ret:
                        LOG.warning("Vision offload: capture failed, retrying…")
                        time.sleep(0.5)
                        continue
                    ok, jpeg = cv2.imencode(".jpg", cam_frame)
                    if not ok:
                        LOG.warning("Vision offload: JPEG encode failed")
                        time.sleep(interval)
                        continue
                    frame = cam_frame
                    frame_bytes = jpeg.tobytes()
                else:
                    file_frame = self._read_frame_from_file()
                    if file_frame is None:
                        time.sleep(interval)
                        continue
                    frame = file_frame
                    ok, jpeg = cv2.imencode(".jpg", frame)
                    if not ok:
                        time.sleep(interval)
                        continue
                    frame_bytes = jpeg.tobytes()
                if frame_bytes:
                    try:
                        LAST_FRAME_PATH.write_bytes(frame_bytes)
                    except Exception as exc:
                        LOG.warning("Vision offload: cannot write last frame: %s", exc)
                    try:
                        RAW_PATH.write_bytes(frame_bytes)
                    except Exception as exc:
                        LOG.warning("Vision offload: cannot write raw snapshot: %s", exc)
                payload = {
                    "ts": time.time(),
                    "frame_jpeg": base64.b64encode(frame_bytes).decode("ascii"),
                    "size": {"w": frame.shape[1], "h": frame.shape[0]},
                }
                try:
                    self._pub.publish(self.topic_out, payload, add_ts=False)
                except Exception as exc:
                    LOG.warning("Vision offload publish error: %s", exc)
                    time.sleep(0.5)
                time.sleep(interval)
        finally:
            provider_state_sub.close()

    def _read_frame_from_file(self):
        try:
            stats = self.frame_file.stat()
            if stats.st_mtime == self._last_file_mtime:
                # no new frame yet; allow small delay
                return None
            data = self.frame_file.read_bytes()
            if not data:
                return None
            arr = np.frombuffer(data, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is not None:
                self._last_file_mtime = stats.st_mtime
            return frame
        except FileNotFoundError:
            return None
        except Exception as exc:
            LOG.warning("Vision offload: cannot read frame file %s: %s", self.frame_file, exc)
            return None


class EnhancedObstacleBridge:
    """Re-publishes enhanced obstacle messages as basic vision.obstacle payloads."""

    def __init__(self) -> None:
        self._sub: BusSub | None = None
        self._pub: BusPub | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread:
            return
        self._stop.clear()
        self._sub = BusSub(TOPIC_VISION_OBSTACLE_ENHANCED)
        self._pub = BusPub()
        self._thread = threading.Thread(target=self._loop, name="vision-enhanced-bridge", daemon=True)
        self._thread.start()
        LOG.info("Vision obstacle bridge started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self._thread = None
        if self._sub:
            try:
                self._sub.close()
            except Exception:
                pass
            self._sub = None
        if self._pub:
            try:
                self._pub.close()
            except Exception:
                pass
            self._pub = None
        LOG.info("Vision obstacle bridge stopped")

    def _loop(self) -> None:
        if not self._sub or not self._pub:
            LOG.error("Vision obstacle bridge missing bus handles")
            return
        while not self._stop.is_set():
            if not is_pc_mode("vision"):
                time.sleep(0.5)
                continue
            try:
                topic, payload = self._sub.recv(timeout_ms=500)
                if not (topic and payload):
                    continue
                simplified = {
                    "type": "obstacle",
                    "present": bool(payload.get("present")),
                    "confidence": float(payload.get("confidence") or 0.0),
                    "ts": payload.get("ts", time.time()),
                    "source": "pc_offload",
                }
                metadata = payload.get("meta") or {}
                if isinstance(metadata, dict):
                    simplified["meta"] = metadata
                self._pub.publish(TOPIC_VISION_OBSTACLE, simplified, add_ts=False)
            except Exception as exc:
                LOG.warning("Vision obstacle bridge error: %s", exc)
                time.sleep(0.2)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    dispatcher = VisionOffloadDispatcher()
    bridge = EnhancedObstacleBridge()
    dispatcher.start()
    bridge.start()

    stop = threading.Event()

    def _graceful_stop(_sig, _frm):
        stop.set()

    signal.signal(signal.SIGINT, _graceful_stop)
    signal.signal(signal.SIGTERM, _graceful_stop)

    try:
        while not stop.is_set():
            time.sleep(0.5)
    finally:
        bridge.stop()
        dispatcher.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
