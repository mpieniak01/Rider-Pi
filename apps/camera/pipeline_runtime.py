"""One camera owner, optional local raw stage, RAM delivery and explicit shutdown."""

from __future__ import annotations

import json
import os
import signal
import threading
import time
import uuid
from pathlib import Path

from apps.camera.pipeline_ipc import FrameServer, LatestFrames
from apps.camera.pipeline_local import LocalProcessor, canonical, image_transform
from services.camera_pipeline_store import native, runtime_path, snapshot
from services.compute_config import _write

IDENTITY = {"rotation": 0, "flip_h": False, "flip_v": False}


def write_status(row):
    # Native encoder callbacks and the main heartbeat can publish concurrently.
    # The shared atomic writer gives each update its own bounded temporary file.
    _write(runtime_path() / "status.json", dict(row, observed_monotonic_ns=time.monotonic_ns()))


class CameraProducer:
    def __init__(self, config, *, frames=None, publisher=None, observation_publisher=None, clock=time.monotonic_ns):
        self.config, self.frames, self.publisher, self.clock = config, frames or LatestFrames(), publisher, clock
        self.observation_publisher, self.last_heartbeat = observation_publisher, 0
        self.created_at = clock()
        self.session, self.sequence = uuid.uuid4().hex, 0
        self.transform = image_transform()
        if self.transform["rotation"] not in {0, 90, 180, 270}:
            raise ValueError("camera_pipeline_rotation_invalid")
        root = runtime_path()
        root.mkdir(parents=True, exist_ok=True)
        epoch = root / "epoch"
        try:
            previous = int(epoch.read_text())
        except (OSError, ValueError):
            previous = 0
        self.epoch = previous + 1
        epoch.write_text(str(self.epoch))
        self.processor = (
            LocalProcessor(config["profile"]["local_engine"])
            if config["profile"]["analysis_location"] == "local"
            else None
        )
        self.status = {
            "state": "starting",
            "active_profile": config["profile"],
            "pipeline_revision": config["revision"],
            "camera_session": self.session,
            "transport_epoch": self.epoch,
            "pid": os.getpid(),
            "error": None,
            "capture_timestamp_source": "sensor" if native(config["profile"]) else None,
            "capture_timestamp_limitation": None,
        }
        self.last_status_at = 0
        write_status(self.status)

    def metadata(self, captured, size, transform):
        self.sequence += 1
        return {
            "contract_version": 1,
            "camera_session": self.session,
            "sequence": self.sequence,
            "transport_epoch": self.epoch,
            "pipeline_revision": self.config["revision"],
            "frame_id": self.session + "-" + str(self.sequence),
            "captured_monotonic_ns": captured,
            "encoded_width": size[0],
            "encoded_height": size[1],
            "image_transform": transform,
        }

    def encoded(self, data, captured, size):
        self.deliver(data, self.metadata(captured, size, self.transform))

    def deliver(self, data, metadata, *, processed=None):
        self.frames.publish(data, metadata)
        if processed is not None:
            self.frames.publish(processed, metadata, view="proc")
        if self.publisher is not None:
            # Legacy consumers receive the source timestamp, never publication time.
            age_s = (self.clock() - metadata["captured_monotonic_ns"]) / 1_000_000_000
            source = dict(
                metadata,
                captured_at=time.time() - age_s,
                timestamp_source="capture",
                id=metadata["sequence"],
            )
            self.publisher.send_multipart([b"camera.frame.raw", json.dumps(source).encode(), data])
        self.status.update(state="active", latest_frame=dict(metadata, sha256=self.frames.frames["raw"][1]["sha256"]))
        if self.clock() - self.last_status_at > 500_000_000:
            self.last_status_at = self.clock()
            write_status(self.status)

    def heartbeat(self):
        latest = self.status.get("latest_frame")
        if self.observation_publisher is None or latest is None or self.clock() - self.last_heartbeat < 1_000_000_000:
            return
        self.last_heartbeat = self.clock()
        age_s = (self.clock() - latest["captured_monotonic_ns"]) / 1_000_000_000
        self.observation_publisher.publish(
            "camera.heartbeat",
            {
                "ts": time.time() - age_s,
                "mode": "pipeline",
                "fps": self.sequence / max(0.001, (self.clock() - self.created_at) / 1_000_000_000),
                "camera_session": self.session,
                "sequence": latest["sequence"],
                "lcd": {"active": False, "presenting": False, "rot": self.transform["rotation"]},
            },
            add_ts=False,
        )

    def array(self, frame, captured):
        import cv2

        raw = canonical(frame, self.transform)
        processed, detections = self.processor.process(raw) if self.processor is not None else (None, [])
        if self.observation_publisher is not None:
            for name, confidence, (x0, y0, x1, y1) in detections:
                if name == "person":
                    self.observation_publisher.publish(
                        "vision.person",
                        {
                            "present": True,
                            "score": confidence,
                            "bbox": [x0, y0, x1 - x0, y1 - y0],
                            "camera_session": self.session,
                            "source_sequence": self.sequence + 1,
                        },
                        add_ts=True,
                    )

        def encode(image):
            ok, result = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if not ok:
                raise RuntimeError("camera_pipeline_encode_failed")
            return result.tobytes()

        data = encode(raw)
        metadata = self.metadata(captured, (raw.shape[1], raw.shape[0]), dict(IDENTITY))
        self.deliver(
            data,
            metadata,
            processed=encode(processed) if processed is not None and self.frames.wanted("proc") else None,
        )
        # Compatibility files exist only in snapshots/local mode, never native MJPEG.
        from apps.camera.frame_metadata import write_metadata

        base = Path(os.getenv("SNAP_DIR", os.getenv("SNAP_BASE", "/home/pi/robot/snapshots")))
        base.mkdir(parents=True, exist_ok=True)
        at = time.time() - (self.clock() - captured) / 1_000_000_000
        for name, payload in (("raw", data),):
            if payload is None:
                continue
            target = base / (name + ".jpg")
            temporary = target.with_suffix(".jpg.tmp")
            temporary.write_bytes(payload)
            os.replace(temporary, target)
            write_metadata(target, captured_at=at, frame_id=metadata["frame_id"], shape=raw.shape)


def _run_native_capture(config, stop, producer):
    started = time.monotonic_ns()
    while not stop.wait(0.5):
        last = (producer.status.get("latest_frame") or {}).get("captured_monotonic_ns", started)
        if time.monotonic_ns() - last > 3_000_000_000:
            raise RuntimeError("camera_pipeline_capture_stalled")
        if snapshot() != config:
            raise RuntimeError("camera_pipeline_configuration_changed")
        producer.heartbeat()
        write_status(producer.status)


def _run_array_capture(camera, config, stop, producer):
    producer.status.update(
        capture_timestamp_source=camera.timestamp_source,
        capture_timestamp_limitation="driver_buffer_age_unknown" if camera.timestamp_source == "read_started" else None,
    )
    while not stop.is_set():
        started = time.monotonic()
        ok, frame, captured = camera.capture()
        if not ok or frame is None:
            raise RuntimeError("camera_pipeline_capture_failed")
        producer.array(frame, captured)
        producer.heartbeat()
        if snapshot() != config:
            raise RuntimeError("camera_pipeline_configuration_changed")
        stop.wait(max(0, 1 / 16 - (time.monotonic() - started)))


def _release_capture_delivery(frames, server, publisher, observation_publisher, released, producer, failed):
    if server is not None:
        server.close()
    else:
        frames.close()
    if publisher is not None:
        publisher.close(linger=0)
    if observation_publisher is not None:
        observation_publisher.close()
    if released and producer is not None and not failed:
        write_status({**producer.status, "state": "stopped", "active_profile": None, "latest_frame": None})


def main():
    config, stop = snapshot(), threading.Event()
    frames, camera, server, publisher = LatestFrames(), None, None, None
    observation_publisher = None
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    for sig in previous:
        signal.signal(sig, lambda *_: stop.set())
    producer = None
    failed = False
    try:
        if not native(config["profile"]):
            import zmq

            publisher = zmq.Context.instance().socket(zmq.PUB)
            publisher.setsockopt(zmq.LINGER, 0)
            publisher.setsockopt(zmq.SNDHWM, 2)
            publisher.bind(os.getenv("FRAME_STREAM_BIND", "tcp://127.0.0.1:5562"))
        from common.bus import BusPub

        observation_publisher = BusPub()
        producer = CameraProducer(
            config, frames=frames, publisher=publisher, observation_publisher=observation_publisher
        )
        server = FrameServer(frames)
        server.start()
        if native(config["profile"]):
            from apps.camera.pipeline_native import NativeCamera

            camera = NativeCamera(producer.encoded)
            _run_native_capture(config, stop, producer)
        else:
            from apps.camera.utils import open_camera

            camera, _ = open_camera((320, 240))
            _run_array_capture(camera, config, stop, producer)
        return 0
    except Exception as exc:
        failed = True
        write_status(
            {
                **(producer.status if producer else {}),
                "state": "failed",
                "active_profile": config["profile"],
                "error": str(exc)[:160],
                "pid": os.getpid(),
            }
        )
        return 1
    finally:
        # Release hardware before declaring the source stopped.
        released = False
        try:
            if camera is not None:
                camera.close()
            released = True
        finally:
            _release_capture_delivery(frames, server, publisher, observation_publisher, released, producer, failed)
            for sig, handler in previous.items():
                signal.signal(sig, handler)
