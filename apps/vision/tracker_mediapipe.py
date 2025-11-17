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

try:
    from apps.vision.ai_mode_adapter import should_run_local_detectors
except ImportError:  # pragma: no cover - fallback for standalone usage
    def should_run_local_detectors() -> bool:  # type: ignore
        return True

BUS_PUB_PORT = int(os.getenv("BUS_PUB_PORT", "5555"))
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
ZMQ_ADDR_PUB = f"tcp://127.0.0.1:{BUS_PUB_PORT}"
ZMQ_ADDR_SUB = f"tcp://127.0.0.1:{BUS_SUB_PORT}"

SNAP_DIR = os.getenv("SNAP_BASE", "/home/pi/robot/snapshots")

# Główne źródło obrazu – klatka z preview_lcd (camera.heartbeat)
LAST_FRAME_PATH = os.getenv("TRACKER_LAST_FRAME_PATH", "/home/pi/robot/data/last_frame.jpg")
TRACKER_PATH = os.path.join(SNAP_DIR, "tracker.jpg")

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
    print(f"[tracker] zmq_pub connected to {ZMQ_ADDR_PUB}", flush=True)
    return s


def zmq_sub(topics: list[str]) -> zmq.Socket:
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.SUB)
    s.connect(ZMQ_ADDR_SUB)
    s.setsockopt(zmq.RCVTIMEO, 100)  # 100ms timeout for responsiveness
    for t in topics:
        s.setsockopt_string(zmq.SUBSCRIBE, t)
        print(f"[tracker] zmq_sub subscribed to topic prefix '{t}'", flush=True)
    print(f"[tracker] zmq_sub connected to {ZMQ_ADDR_SUB}", flush=True)
    return s


def pub(topic: str, payload: dict[str, Any]) -> None:
    try:
        assert PUB is not None
        message = f"{topic} {json.dumps(payload, ensure_ascii=False)}"
        PUB.send_string(message)
        print(f"[tracker] pub → {topic} {payload}", flush=True)
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
    except Exception as e:
        print(f"[tracker] sub_recv err: {e}", flush=True)
        return "", {}


def control_loop() -> None:
    """Listen for tracking mode control messages and camera heartbeats."""
    global FOLLOW_MODE, LAST_FRAME_PATH
    print("[tracker] control_loop started", flush=True)

    while True:
        try:
            topic, data = sub_recv()
            if not topic and not data:
                continue

            # Kamera – serce systemu: aktualizujemy ścieżkę do klatki
            if topic == "camera.heartbeat":
                lfp = data.get("last_frame_path")
                if isinstance(lfp, str) and lfp:
                    LAST_FRAME_PATH = lfp
                # można też kiedyś wykorzystać fps, lcd, itp.
                # print(f"[tracker] heartbeat last_frame_path={LAST_FRAME_PATH}", flush=True)
                continue

            if topic == "tracking.mode:set":
                # Nowe API sterowania trackingiem (alias dla tracking.mode)
                print(f"[tracker] tracking.mode:set data={data}", flush=True)

            # Interesują nas tylko tematy związane z trackingiem
            if "tracking" not in topic:
                continue

            # Debug: pokaż wszystkie potencjalne sterowania
            if "mode" in data or "enabled" in data:
                print(f"[tracker] tracking control topic='{topic}' data={data}", flush=True)

            mode_raw = str(data.get("mode", "none"))
            enabled = bool(data.get("enabled", True))

            mode_norm = mode_raw.strip().lower()

            with FOLLOW_MODE_LOCK:
                if not enabled or mode_norm in ("none", "off", "disable", "disabled", ""):
                    FOLLOW_MODE = "NONE"
                    print(
                        f"[tracker] mode → NONE (enabled={enabled}, raw='{mode_raw}')",
                        flush=True,
                    )
                elif mode_norm in ("face", "hand"):
                    FOLLOW_MODE = mode_norm.upper()
                    print(
                        f"[tracker] mode → {FOLLOW_MODE} (enabled={enabled})",
                        flush=True,
                    )
                else:
                    print(
                        f"[tracker] invalid tracking mode '{mode_raw}' (enabled={enabled}) in data={data}",
                        flush=True,
                    )

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[tracker] control_loop err: {e}", flush=True)
            time.sleep(0.1)


def calculate_offset_x(detections: list, frame_width: float | None = None) -> float | None:
    """
    Calculate horizontal offset from center.
    Returns offset_x in range [-1.0, 1.0], or None if no detection.
    frame_width can be provided when detections use absolute pixel coordinates.
    -1.0 = far left, 0.0 = center, +1.0 = far right
    """
    if not detections:
        return None

    det = detections[0]

    if hasattr(det, "location_data") and det.location_data.HasField("relative_bounding_box"):
        bbox = det.location_data.relative_bounding_box
        center_x = bbox.xmin + bbox.width / 2.0
        if frame_width is not None and center_x > 1.0:
            center_x /= frame_width
    elif hasattr(det, "landmark"):
        center_x = det.landmark[0].x
        if frame_width is not None and center_x > 1.0:
            center_x /= frame_width
    else:
        return None

    offset_x = (center_x - 0.5) * 2.0  # Convert to [-1,1]
    if abs(offset_x) < DEAD_ZONE:
        offset_x = 0.0

    return offset_x


def save_tracker_frame(frame_bgr: Any) -> bool:
    """Save annotated tracker frame to disk atomically."""
    try:
        os.makedirs(SNAP_DIR, exist_ok=True)
        ok, encoded = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            return False
        tmp_path = TRACKER_PATH + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(encoded.tobytes())
        os.replace(tmp_path, TRACKER_PATH)
        return True
    except Exception as e:
        print(f"[tracker] save_tracker_frame error: {e}", flush=True)
        return False


def tracking_loop() -> None:
    """Main tracking loop using MediaPipe on frames from last_frame.jpg."""
    global LAST_FRAME_PATH

    print("[tracker] tracking_loop started", flush=True)

    mp_face = mp.solutions.face_detection
    mp_hands = mp.solutions.hands

    face_detector = mp_face.FaceDetection(model_selection=0, min_detection_confidence=0.5)
    hand_detector = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    frame_interval = 1.0 / MAX_FPS
    last_pub_ts = 0.0
    tracker_active = False

    # FPS calculation
    fps_start_time = time.time()
    fps_frame_count = 0
    fps_value = 0.0

    while True:
        try:
            if not should_run_local_detectors():
                if tracker_active:
                    print("[tracker] vision provider switched to PC -> pausing local tracker", flush=True)
                tracker_active = False
                time.sleep(0.25)
                continue
            if not tracker_active:
                print("[tracker] vision provider local -> resuming tracker", flush=True)
            tracker_active = True

            t0 = time.time()
            with FOLLOW_MODE_LOCK:
                mode = FOLLOW_MODE

            if mode == "NONE":
                # tryb wyłączony – nie przetwarzamy klatek
                time.sleep(0.1)
                continue

            # Wczytujemy ostatnią klatkę z preview
            frame = cv2.imread(LAST_FRAME_PATH)
            if frame is None:
                print(f"[tracker] cannot read frame from {LAST_FRAME_PATH}", flush=True)
                time.sleep(0.05)
                continue

            fps_frame_count += 1
            if t0 - fps_start_time >= 1.0:
                fps_value = fps_frame_count / (t0 - fps_start_time)
                fps_start_time = t0
                fps_frame_count = 0

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = rgb_frame.shape[:2]

            offset_x = None
            detections = None

            if mode == "FACE":
                results = face_detector.process(rgb_frame)
                if results.detections:
                    offset_x = calculate_offset_x(results.detections)
                    detections = results.detections
                    print(
                        f"[tracker] DETECTION FACE count={len(results.detections)} offset_x={offset_x}",
                        flush=True,
                    )
                else:
                    print("[tracker] DETECTION FACE none", flush=True)
            elif mode == "HAND":
                results = hand_detector.process(rgb_frame)
                if results.multi_hand_landmarks:
                    offset_x = calculate_offset_x(results.multi_hand_landmarks)
                    detections = results.multi_hand_landmarks
                    print(
                        f"[tracker] DETECTION HAND count={len(results.multi_hand_landmarks)} offset_x={offset_x}",
                        flush=True,
                    )
                else:
                    print("[tracker] DETECTION HAND none", flush=True)
            else:
                print(f"[tracker] Unknown mode '{mode}'", flush=True)

            annotated_frame = frame.copy()

            # FPS overlay
            fps_text = f"FPS: {fps_value:.1f}"
            cv2.putText(
                annotated_frame,
                fps_text,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            # Detection marker
            if detections is not None and len(detections) > 0:
                det = detections[0]
                center_x, center_y = None, None

                if hasattr(det, "location_data") and det.location_data.HasField("relative_bounding_box"):
                    bbox = det.location_data.relative_bounding_box
                    center_x = int((bbox.xmin + bbox.width / 2.0) * w)
                    center_y = int((bbox.ymin + bbox.height / 2.0) * h)
                    radius = int(max(bbox.width, bbox.height) * w / 2.0)
                elif hasattr(det, "landmark") and len(det.landmark) > 0:
                    center_x = int(det.landmark[0].x * w)
                    center_y = int(det.landmark[0].y * h)
                    radius = 40
                else:
                    radius = 40

                if center_x is not None and center_y is not None:
                    cv2.circle(annotated_frame, (center_x, center_y), radius, (0, 255, 255), 2)
                    cv2.circle(annotated_frame, (center_x, center_y), 5, (0, 255, 255), -1)

            # Zapisujemy ramkę trackera zawsze przy aktywnym trybie
            save_tracker_frame(annotated_frame)

            now = time.time()
            if offset_x is not None and (now - last_pub_ts) >= frame_interval:
                pub(
                    "vision.tracking.offset",
                    {"offset_x": round(offset_x, 3), "mode": mode.lower(), "ts": now},
                )
                last_pub_ts = now
            else:
                if offset_x is None:
                    print("[tracker] no offset to publish", flush=True)
                else:
                    print(
                        f"[tracker] publish skipped (interval) offset_x={offset_x}",
                        flush=True,
                    )

            elapsed = time.time() - t0
            sleep_time = max(0.0, frame_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[tracker] tracking_loop err: {e}", flush=True)
            time.sleep(0.1)

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
    # Subskrybujemy tematy sterujące nowym API + heartbeat kamery
    SUB = zmq_sub(
        [
            "tracking.mode",
            "tracking.mode:set",
            "camera.heartbeat",
        ]
    )

    threading.Thread(target=control_loop, daemon=True).start()
    tracking_loop()
