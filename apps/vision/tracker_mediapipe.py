#!/usr/bin/env python3
"""
apps/vision/tracker_mediapipe.py
MediaPipe-based face and hand tracking for Follow Me mode.
Subscribes to control topics and publishes tracking offset.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

import cv2
import mediapipe as mp
import zmq

BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
ZMQ_ADDR_PUB = f"tcp://127.0.0.1:{BUS_PUB_PORT}"
ZMQ_ADDR_SUB = f"tcp://127.0.0.1:{BUS_SUB_PORT}"

SNAP_DIR = os.getenv("SNAP_BASE", "/home/pi/robot/snapshots")
RAW_PATH = os.path.join(SNAP_DIR, "cam.jpg")

# Tracking parameters
DEAD_ZONE = float(os.getenv("TRACKING_DEAD_ZONE", "0.1"))  # ±10% center is "good enough"
MAX_FPS = float(os.getenv("TRACKING_MAX_FPS", "10.0"))  # Limit CPU usage

PUB: zmq.Socket | None = None
SUB: zmq.Socket | None = None
FOLLOW_MODE_LOCK = threading.Lock()
FOLLOW_MODE: str = "NONE"  # "NONE", "FACE", "HAND"


def zmq_pub() -> zmq.Socket:
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.PUB)
    s.connect(ZMQ_ADDR_PUB)
    return s


def zmq_sub(topics: list[str]) -> zmq.Socket:
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.SUB)
    s.connect(ZMQ_ADDR_SUB)
    s.setsockopt(zmq.RCVTIMEO, 100)  # 100ms timeout for responsiveness
    for t in topics:
        s.setsockopt_string(zmq.SUBSCRIBE, t)
    return s


def pub(topic: str, payload: dict[str, Any]) -> None:
    try:
        assert PUB is not None
        PUB.send_string(f"{topic} {json.dumps(payload, ensure_ascii=False)}")
    except Exception as e:
        print(f"[tracker] pub err: {e}", flush=True)


def _json_loads(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        return {}


def sub_recv() -> tuple[str, dict[str, Any]]:
    """Receive message from SUB socket."""
    assert SUB is not None
    try:
        parts = SUB.recv_multipart()
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


def control_loop() -> None:
    """Listen for tracking mode control messages."""
    global FOLLOW_MODE
    print("[tracker] control_loop started", flush=True)

    while True:
        try:
            topic, data = sub_recv()
            if not topic:
                continue

            with FOLLOW_MODE_LOCK:
                if topic == "vision.follow.face.set":
                    FOLLOW_MODE = "FACE"
                    print("[tracker] mode → FACE", flush=True)
                elif topic == "vision.follow.hand.set":
                    FOLLOW_MODE = "HAND"
                    print("[tracker] mode → HAND", flush=True)
                elif topic == "vision.follow.stop":
                    FOLLOW_MODE = "NONE"
                    print("[tracker] mode → NONE", flush=True)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[tracker] control_loop err: {e}", flush=True)
            time.sleep(0.1)


def open_camera():
    """Open camera for capturing frames."""
    try:
        from picamera2 import Picamera2

        picam2 = Picamera2()
        cfg = picam2.create_preview_configuration(main={"size": (320, 240), "format": "RGB888"})
        picam2.configure(cfg)
        picam2.start()

        def read():
            arr = picam2.capture_array()
            return True, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

        return read
    except (ImportError, RuntimeError) as e:
        print(f"[tracker] PiCamera2 not available, using cv2.VideoCapture: {e}", flush=True)
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        return cap.read


def calculate_offset_x(detections: list, frame_width: float | None = None) -> float | None:
    """
    Calculate horizontal offset from center.
    Returns offset_x in range [-1.0, 1.0], or None if no detection.
    frame_width can be provided when detections use absolute pixel coordinates.
    -1.0 = far left, 0.0 = center, +1.0 = far right
    """
    if not detections:
        return None

    # Take first detection (could be improved to choose largest/closest)
    det = detections[0]

    # For face detection, use bbox
    if hasattr(det, "location_data") and det.location_data.HasField("relative_bounding_box"):
        bbox = det.location_data.relative_bounding_box
        center_x = bbox.xmin + bbox.width / 2.0
        if frame_width is not None and center_x > 1.0:
            center_x /= frame_width
    # For hand detection, use landmark (wrist = landmark 0)
    elif hasattr(det, "landmark"):
        center_x = det.landmark[0].x
        if frame_width is not None and center_x > 1.0:
            center_x /= frame_width
    else:
        return None

    # Convert to offset: center_x is in [0, 1], where 0.5 is center
    offset_x = (center_x - 0.5) * 2.0  # Convert to [-1, 1]

    # Apply dead zone
    if abs(offset_x) < DEAD_ZONE:
        offset_x = 0.0

    return offset_x


def tracking_loop() -> None:
    """Main tracking loop using MediaPipe."""
    print("[tracker] tracking_loop started", flush=True)

    # Initialize MediaPipe
    mp_face = mp.solutions.face_detection
    mp_hands = mp.solutions.hands

    face_detector = mp_face.FaceDetection(model_selection=0, min_detection_confidence=0.5)
    hand_detector = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    read = open_camera()
    frame_interval = 1.0 / MAX_FPS
    last_pub_ts = 0.0

    while True:
        try:
            t0 = time.time()

            # Get current mode
            with FOLLOW_MODE_LOCK:
                mode = FOLLOW_MODE

            # Skip processing if no tracking active
            if mode == "NONE":
                time.sleep(0.1)
                continue

            # Read frame
            ok, frame = read()
            if not ok:
                time.sleep(0.01)
                continue

            # Convert to RGB for MediaPipe
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = rgb_frame.shape[:2]

            offset_x = None

            # Process based on mode
            if mode == "FACE":
                results = face_detector.process(rgb_frame)
                if results.detections:
                    offset_x = calculate_offset_x(results.detections)
            elif mode == "HAND":
                results = hand_detector.process(rgb_frame)
                if results.multi_hand_landmarks:
                    # Convert hand landmarks to detection-like format
                    offset_x = calculate_offset_x(results.multi_hand_landmarks)

            # Publish offset if detected and enough time passed
            now = time.time()
            if offset_x is not None and (now - last_pub_ts) >= frame_interval:
                pub(
                    "vision.tracking.offset",
                    {"offset_x": round(offset_x, 3), "mode": mode.lower(), "ts": now},
                )
                last_pub_ts = now

            # Rate limiting
            elapsed = time.time() - t0
            sleep_time = max(0.0, frame_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[tracker] tracking_loop err: {e}", flush=True)
            time.sleep(0.1)

    # Clean up detectors
    try:
        if hasattr(face_detector, "close"):
            face_detector.close()
        if hasattr(hand_detector, "close"):
            hand_detector.close()
    except Exception as e:
        print(f"[tracker] detector cleanup warning: {e}", flush=True)


if __name__ == "__main__":
    print("[tracker] starting MediaPipe tracker", flush=True)
    PUB = zmq_pub()
    SUB = zmq_sub(["vision.follow.face.set", "vision.follow.hand.set", "vision.follow.stop"])

    # Start control listener in background
    threading.Thread(target=control_loop, daemon=True).start()

    # Run tracking loop in main thread
    tracking_loop()
