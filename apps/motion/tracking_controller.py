#!/usr/bin/env python3
"""
apps/motion/tracking_controller.py

Subskrybuje vision.tracking.offset i wystawia komendy ruchu na bus:
- cmd.move {vx, vy, yaw, duration, rid, prio, ts}
- cmd.stop {rid, reason, ts}

Regulator P z martwą strefą i watchdogiem. NIE steruje sprzętem bezpośrednio
(od tego jest rider-motion-bridge), dzięki czemu warstwa WEB i TRACKING są
niezależne i odporne na awarie jednej z nich.

Tunable (ENV):
- TRACKING_KP (default 0.15)
- TRACKING_DEAD_ZONE (default 0.10)
- TRACKING_TIMEOUT (s, default 1.0)
- TRACKING_MAX_SPEED (default 0.20, 0..1)
- TRACKING_CMD_DURATION (s, default 0.20)  # czas „dawki” ruchu
- TRACKING_CMD_PRIO (int, default 50)      # priorytet źródła „tracking”
- BUS_SUB_PORT (default 5556)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

import zmq

from common.bus import BusPub  # publikujemy tylko na bus

# ── Konfiguracja ──────────────────────────────────────────────────────────────
BUS_SUB_PORT = int(os.getenv("BUS_SUB_PORT", "5556"))
ZMQ_ADDR_SUB = f"tcp://127.0.0.1:{BUS_SUB_PORT}"

KP = float(os.getenv("TRACKING_KP", "0.15"))
DEAD_ZONE = float(os.getenv("TRACKING_DEAD_ZONE", "0.10"))
TIMEOUT_SEC = float(os.getenv("TRACKING_TIMEOUT", "1.0"))
MAX_SPEED = float(os.getenv("TRACKING_MAX_SPEED", "0.20"))
CMD_DURATION = float(os.getenv("TRACKING_CMD_DURATION", "0.20"))
CMD_PRIO = int(os.getenv("TRACKING_CMD_PRIO", "50"))
RID = "tracking"  # identyfikator źródła
LOOP_HZ = 10.0  # tylko do logu informacyjnego

log = logging.getLogger("tracking_controller")
logging.basicConfig(
    level=os.getenv("TRACKING_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def _json_loads(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        return {}


def _zmq_sub(topics) -> zmq.Socket:
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.SUB)
    s.connect(ZMQ_ADDR_SUB)
    s.setsockopt(zmq.RCVTIMEO, 100)  # 100 ms
    for t in topics:
        s.setsockopt_string(zmq.SUBSCRIBE, t)
    return s


def _sub_recv(sock: zmq.Socket) -> tuple[str, dict[str, Any]]:
    """Odbierz (topic, payload_json) z SUB."""
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


class TrackingController:
    def __init__(self) -> None:
        self.bus = BusPub(warmup_ms=5)
        self.lock = threading.Lock()
        self.last_offset_ts = 0.0
        self.current_mode = "NONE"

        log.info(
            "[tracking_controller] params: KP=%.3f DEAD=%.3f TIMEOUT=%.2fs MAX=%.3f DURATION=%.2fs PRIO=%d HZ=%.1f",
            KP,
            DEAD_ZONE,
            TIMEOUT_SEC,
            MAX_SPEED,
            CMD_DURATION,
            CMD_PRIO,
            LOOP_HZ,
        )

    # ── Publikacja na busie (kontrakt cmd.move / cmd.stop) ────────────────────
    def _send_move(
        self,
        yaw: float,
        duration: float = CMD_DURATION,
        vx: float = 0.0,
        vy: float = 0.0,
    ) -> None:
        msg = {
            "vx": float(vx),
            "vy": float(vy),
            "yaw": float(yaw),
            "duration": float(duration),
            "rid": RID,
            "prio": int(CMD_PRIO),
            "ts": time.time(),
        }
        self.bus.publish("cmd.move", msg, add_ts=False)  # ts już w msg

    def _send_stop(self, reason: str) -> None:
        msg = {
            "rid": RID,
            "reason": str(reason),
            "ts": time.time(),
        }
        self.bus.publish("cmd.stop", msg, add_ts=False)

    # ── Logika regulatora ─────────────────────────────────────────────────────
    def on_tracking_offset(self, offset_x: float, mode: str) -> None:
        """offset_x: -1.0 (lewo) .. +1.0 (prawo), 0.0 = center."""
        now = time.time()
        with self.lock:
            self.last_offset_ts = now
            self.current_mode = mode

            if abs(offset_x) < DEAD_ZONE:
                log.info("[tracking] STOP (dead-zone)")
                self._send_stop("dead-zone")
                return

            # regulator P
            az = KP * offset_x  # yaw docelowy
            az = max(-MAX_SPEED, min(MAX_SPEED, az))  # clamp [-MAX_SPEED, +MAX_SPEED]

            direction = "right" if az > 0 else "left"
            log.info(
                "[tracking] rotate %s @ %.3f (offset=%.3f, mode=%s)",
                direction,
                abs(az),
                offset_x,
                mode,
            )

            # publikacja dawki ruchu na busie
            self._send_move(yaw=az, duration=CMD_DURATION)

    def watchdog_loop(self) -> None:
        """Stop, gdy brak update'ów przez TIMEOUT_SEC."""
        while True:
            try:
                time.sleep(0.2)
                now = time.time()
                with self.lock:
                    if self.current_mode != "NONE" and now - self.last_offset_ts > TIMEOUT_SEC:
                        log.info(
                            "[tracking] timeout (%.1fs) - stopping",
                            now - self.last_offset_ts,
                        )
                        self._send_stop("timeout")
                        self.current_mode = "NONE"
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.warning("[tracking] watchdog error: %s", e)
                time.sleep(0.2)


def main() -> None:
    log.info("[tracking_controller] starting")
    ctrl = TrackingController()

    threading.Thread(target=ctrl.watchdog_loop, daemon=True).start()

    sub = _zmq_sub(["vision.tracking.offset"])
    log.info("[tracking_controller] listening for tracking offset...")

    try:
        while True:
            topic, data = _sub_recv(sub)
            if topic != "vision.tracking.offset":
                continue
            offset_x = float(data.get("offset_x", 0.0))
            mode = str(data.get("mode", "unknown"))
            ctrl.on_tracking_offset(offset_x, mode)
    except KeyboardInterrupt:
        log.info("[tracking_controller] interrupted")
    finally:
        try:
            ctrl._send_stop("shutdown")
        finally:
            log.info("[tracking_controller] shutdown complete")


if __name__ == "__main__":
    main()
