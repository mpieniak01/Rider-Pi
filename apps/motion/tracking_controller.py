#!/usr/bin/env python3
"""Explicit follow task producer; never owns UART or changes consent."""

from __future__ import annotations

import logging
import math
import threading
import time

from apps.motion.config import load_config
from apps.safety.intent import read_service_intent, write_intent_status
from apps.safety.state import read_status
from common.bus import BusPub, BusSub

_cfg = load_config()
KP = _cfg.kp
DEAD_ZONE = _cfg.dead_zone
TIMEOUT_SEC = _cfg.timeout_s
MAX_SPEED = _cfg.max_speed
CMD_DURATION = min(0.25, _cfg.cmd_duration)
CMD_PRIO = _cfg.cmd_prio
RID = "tracking"
UNIT = "rider-tracking-controller.service"
log = logging.getLogger("tracking_controller")


class TrackingController:
    def __init__(
        self,
        *,
        bus=None,
        status_reader=read_status,
        intent_reader=read_service_intent,
        intent_writer=write_intent_status,
    ):
        self.bus = bus if bus is not None else BusPub(warmup_ms=5)
        self.status_reader = status_reader
        self.intent_reader = intent_reader
        self.intent_writer = intent_writer
        self.last_intent_status = 0.0
        self.publisher_thread = threading.get_ident()
        self.last_offset_ts = 0.0
        self.current_mode = "NONE"
        self.generation = None
        self.intent_id = None
        self.intent_ts = 0.0
        self.sequence = -1
        log.info("passive until a current follow_me task intent and consent")

    def _authorized_envelope(self, action: str) -> dict | None:
        state = self.status_reader()
        if not state.get("can_move") or state.get("owner") != "follow_me":
            return None
        intent = self.intent_reader(UNIT, state.get("generation"))
        if not intent:
            return None
        if self.generation != intent["generation"] or self.intent_id != intent["request_id"]:
            self.generation = intent["generation"]
            self.intent_id = intent["request_id"]
            self.intent_ts = intent["ts"]
            self.sequence = max(intent["seq"], int(state.get("last_seq", -1)))
            self.current_mode = "NONE"
            self.last_intent_status = 0.0
        if time.monotonic() - self.last_intent_status >= 0.5:
            if not self.intent_writer(UNIT, intent, active=True):
                self._send_stop("tracking_intent_status_unavailable")
                return None
            self.last_intent_status = time.monotonic()
        self.sequence = max(self.sequence, int(state.get("last_seq", -1))) + 1
        return {
            "action": action,
            "source": "follow_me",
            "settings_revision": (state.get("manual_settings") or {}).get("revision"),
            "generation": self.generation,
            "seq": self.sequence,
            "ts": time.time(),
            "ttl_ms": 250,
            "request_id": f"tracking-{self.generation}-{self.sequence}",
        }

    def _publish(self, command):
        if threading.get_ident() != self.publisher_thread:
            raise RuntimeError("Tracking BUS publisher belongs to the controller thread")
        self.bus.publish("motion.command", command, add_ts=False)

    def _send_move(self, yaw: float, duration: float = CMD_DURATION, vx: float = 0.0, vy: float = 0.0):
        envelope = self._authorized_envelope("move")
        if envelope is not None:
            self._publish(
                {
                    **envelope,
                    "vx": float(vx),
                    "vy": float(vy),
                    "yaw": float(yaw),
                    "duration": min(0.25, float(duration)),
                    "rid": RID,
                }
            )

    def _send_stop(self, reason: str):
        state = self.status_reader()
        if state.get("owner") == "follow_me" and state.get("generation") == self.generation:
            self._publish({"action": "stop", "source": "follow_me", "reason": reason})

    def on_tracking_offset(self, offset_x: float, mode: str, *, observed_at=None):
        if isinstance(offset_x, bool) or isinstance(observed_at, bool):
            return
        try:
            offset_x, observed = float(offset_x), float(observed_at)
        except (ValueError, TypeError, OverflowError):
            return
        now = time.time()
        if not math.isfinite(offset_x) or not math.isfinite(observed) or not -1 <= offset_x <= 1:
            return
        if not -0.1 <= now - observed <= min(TIMEOUT_SEC, 0.5):
            return
        envelope = self._authorized_envelope("move")
        if envelope is None or observed < self.intent_ts:
            return
        self.last_offset_ts = observed
        self.current_mode = mode
        yaw = 0.0 if abs(offset_x) < DEAD_ZONE else max(-MAX_SPEED, min(MAX_SPEED, KP * offset_x))
        self._publish({**envelope, "vx": 0.0, "yaw": yaw, "duration": CMD_DURATION, "rid": RID})

    def watchdog_tick(self):
        # Bind a newly authorized task even while waiting for its first target.
        self._authorized_envelope("move")
        if self.current_mode != "NONE" and time.time() - self.last_offset_ts > TIMEOUT_SEC:
            self._send_stop("tracking_observation_timeout")
            self.current_mode = "NONE"

    def watchdog_loop(self):
        """Compatibility entry point; run on the owning publisher thread."""
        while True:
            self.watchdog_tick()
            time.sleep(0.2)


def main():
    logging.basicConfig(level=_cfg.log_level)
    ctrl = TrackingController()
    with BusSub(["vision.tracking.offset"]) as subscriber:
        try:
            while True:
                topic, data = subscriber.recv(timeout_ms=100)
                ctrl.watchdog_tick()
                if topic == "vision.tracking.offset" and isinstance(data, dict):
                    ctrl.on_tracking_offset(
                        data.get("offset_x"), str(data.get("mode", "unknown")), observed_at=data.get("ts")
                    )
        except KeyboardInterrupt:
            pass
        finally:
            try:
                ctrl._send_stop("tracking_shutdown")
            finally:
                ctrl.bus.close()


if __name__ == "__main__":
    main()
