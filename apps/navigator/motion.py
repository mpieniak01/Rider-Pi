"""Task authorization and canonical motion envelopes without hardware ownership."""

from __future__ import annotations

import os
import time

from apps.navigator.state import NavigatorState
from apps.safety.intent import read_service_intent, write_intent_status

CMD_DURATION = float(os.getenv("NAVIGATOR_CMD_DURATION", "0.3"))


class MotionProducer:
    def _accept_motion_request(self, payload):
        from apps.navigator.safety import authorize_request

        try:
            envelope, _ = authorize_request(payload)
        except (ValueError, TypeError, OverflowError):
            return False
        generation = envelope["generation"]
        previous = getattr(self, "_control_seq", -1) if getattr(self, "_motion_generation", None) == generation else -1
        if envelope["seq"] <= previous:
            return False
        self._motion_generation = generation
        self._control_seq = envelope["seq"]
        self._request_id = envelope["request_id"]
        return True

    def _consume_task_intent(self):
        """Accept a journaled explicit task once, only in its current consent lease."""
        from apps.safety.state import read_status

        state = read_status()
        intent = read_service_intent("rider-navigator.service", state.get("generation"))
        if state.get("can_move") is not True or state.get("owner") != "navigation" or not intent:
            if self.active or self.state == NavigatorState.RETURNING_HOME:
                self.active = False
                self.state = NavigatorState.STOPPED
                self._send_motion_stop()
            return
        identity = (intent["generation"], intent["request_id"])
        if identity != self._consumed_intent:
            self._intent = intent
            self._motion_generation = intent["generation"]
            self._control_seq = intent["seq"]
            self._motion_seq = max(intent["seq"], state.get("last_seq", -1))
            self._request_id = intent["request_id"]
            # Claim before any command. An earlier process cannot replay this task.
            if not write_intent_status("rider-navigator.service", intent, active=False):
                self._send_motion_stop()
                self.active = False
                self.state = NavigatorState.STOPPED
                return
            self._consumed_intent = identity
            self.start()
        if time.monotonic() - self._intent_status_at >= 0.5:
            executing = (self.active and self.state in {NavigatorState.EXPLORING, NavigatorState.AVOIDING}) or (
                self.state == NavigatorState.RETURNING_HOME
            )
            if not write_intent_status("rider-navigator.service", intent, active=executing):
                self._send_motion_stop()
                self.active = False
                self.state = NavigatorState.STOPPED
                return
            self._intent_status_at = time.monotonic()

    def _send_motion_drive(self, lx: float, az: float = 0.0, duration: float | None = None):
        """Use only the generation authorized for this navigation task."""
        from services.safety_contract import read_status

        safety = read_status()
        generation = getattr(self, "_motion_generation", None)
        if (
            safety.get("can_move") is not True
            or safety.get("owner") != "navigation"
            or generation is None
            or safety.get("generation") != generation
        ):
            self.active = False
            self.state = NavigatorState.STOPPED
            return
        self._motion_seq = max(getattr(self, "_motion_seq", 0), safety.get("last_seq", -1)) + 1
        self.pub.publish(
            "motion.command",
            {
                "action": "move",
                "source": "navigation",
                "generation": generation,
                "seq": self._motion_seq,
                "ts": time.time(),
                "ttl_ms": 250,
                "vx": max(-1.0, min(1.0, float(lx))),
                "yaw": max(-1.0, min(1.0, float(az))),
                "duration": min(0.25, max(0.01, float(duration if duration is not None else CMD_DURATION))),
                "request_id": f"navigation-{generation}-{self._motion_seq}",
            },
        )

    def _send_motion_stop(self):
        """An optional navigator releases only its own authorized task."""
        from services.safety_contract import read_status

        safety = read_status()
        if safety.get("owner") == "navigation" and safety.get("generation") == getattr(
            self, "_motion_generation", None
        ):
            self.pub.publish("motion.command", {"action": "stop", "source": "navigation", "ts": time.time()})
        self._motion_generation = None
