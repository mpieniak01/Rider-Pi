"""Task authorization and canonical motion envelopes without hardware ownership."""

from __future__ import annotations

import os

from apps.navigator.state import NavigatorState
from apps.safety.intent import read_service_intent, write_intent_status
from common.data_quality import finite_number

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
        self._request_generation = generation
        self._intent_start_ts = envelope["ts"]
        self._clear_plan()
        self._passive_planning = False
        self._data_blocked = False
        # Replacing operator intent cannot erase motion already sent to SDK.
        self._motion_started = getattr(self, "_motion_started", False)
        return True

    def _consume_task_intent(self):
        """Accept a journaled explicit task once, only in its current consent lease."""
        from apps.safety.state import read_status

        if self._passive_planning:
            # Canonical STOP revoked motion consent, while this bounded map
            # response is a read-only plan. Do not turn lease loss into a race
            # that discards the response or ever reacquire actuator authority.
            if self._intent and self.clock() - self._intent_status_at >= 0.5:
                write_intent_status(
                    "rider-navigator.service",
                    self._intent,
                    active=False,
                    data_ready=self.navigation_quality()["data_ready"],
                    navigation_ready=False,
                    data_error=self.navigation_quality()["data_error"],
                )
                self._intent_status_at = self.clock()
            return
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
            self._request_generation = intent["generation"]
            self._intent_start_ts = intent["ts"]
            self._data_blocked = False
            self._motion_started = getattr(self, "_motion_started", False)
            # Claim before any command. An earlier process cannot replay this task.
            if not write_intent_status("rider-navigator.service", intent, active=False):
                self._send_motion_stop()
                self.active = False
                self.state = NavigatorState.STOPPED
                return
            self._consumed_intent = identity
            self.start()
        if self.clock() - self._intent_status_at >= 0.5:
            executing = (self.active and self.state in {NavigatorState.EXPLORING, NavigatorState.AVOIDING}) or (
                self.state == NavigatorState.RETURNING_HOME
            )
            if not write_intent_status(
                "rider-navigator.service",
                intent,
                active=executing,
                **{
                    key: value
                    for key, value in self.navigation_quality().items()
                    if key in {"data_ready", "navigation_ready", "data_error"}
                },
            ):
                self._send_motion_stop()
                self.active = False
                self.state = NavigatorState.STOPPED
                return
            self._intent_status_at = self.clock()

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
            if self._motion_started:
                self._quality_failure("motion_authority_lost", stop=True)
            self.active = False
            self.state = NavigatorState.STOPPED
            return
        if not finite_number(lx) or not finite_number(az):
            self._quality_failure("invalid_motion_vector", stop=True)
            return
        if not self._motion_data_permitted(lx, az):
            return
        command_duration = duration if duration is not None else CMD_DURATION
        if not finite_number(command_duration) or command_duration <= 0:
            self._quality_failure("invalid_motion_duration", stop=True)
            return
        self._motion_seq = max(getattr(self, "_motion_seq", 0), safety.get("last_seq", -1)) + 1
        self.pub.publish(
            "motion.command",
            {
                "action": "move",
                "source": "navigation",
                "settings_revision": (safety.get("manual_settings") or {}).get("revision"),
                "generation": generation,
                "seq": self._motion_seq,
                "ts": self.wall_clock(),
                "ttl_ms": 250,
                "vx": max(-1.0, min(1.0, float(lx))),
                "yaw": max(-1.0, min(1.0, float(az))),
                "duration": min(0.25, max(0.01, command_duration)),
                "request_id": f"navigation-{generation}-{self._motion_seq}",
            },
        )
        self._motion_started = self._motion_started or lx != 0 or az != 0

    def _send_motion_stop(self):
        """An optional navigator releases only its own authorized task."""
        from services.safety_contract import read_status

        safety = read_status()
        if safety.get("owner") == "navigation" and safety.get("generation") == getattr(
            self, "_motion_generation", None
        ):
            self.pub.publish("motion.command", {"action": "stop", "source": "navigation", "ts": self.wall_clock()})
        self._motion_generation = None
