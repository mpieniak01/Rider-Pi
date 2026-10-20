"""One bounded navigation capture/request/decision cycle."""

import hashlib
import socket
import time
import urllib.error

from apps.compute.client import ComputeError


class NavigationCycle:
    def _run_cycle(self, source):
        self._start_cycle()
        received = self._receive_frame(source)
        if received is None:
            return
        frame, age = received
        captured, meta = self._frame_metadata(age)
        received, decision = self._request_decision(meta, frame, captured)
        if not received:
            return
        if self.policy["mode"] == "drive":
            admitted, decision = self._apply_decision(decision, meta, captured)
            if not admitted:
                return
        self._finish_cycle(decision)

    def _receive_frame(self, source):
        frame = self._timed("frame_wait_ms", source.recv, 50)
        if not self._frame_arrived(frame):
            return None
        if self.lease.journey is not None and not self.lease.journey.validate_capture(frame):
            raise ComputeError("navigation_journey_source_changed")
        self.last_frame = (frame["input_id"], frame["captured_at"])
        source = frame.get("source")
        self.last_source = (
            {key: source.get(key) for key in ("camera_session", "transport_epoch", "pipeline_revision")}
            if isinstance(source, dict)
            else None
        )
        if self.policy["mode"] == "drive" and isinstance(frame["data"], bytes) and len(frame["data"]) <= 512 * 1024:
            self.frame_trace.append(frame)
        source_mono = frame.get("captured_monotonic_ns")
        age = (
            (self.clock() - source_mono / 1_000_000_000) * 1000
            if type(source_mono) is int
            else (time.time() - frame["captured_at"]) * 1000
        )
        if not 0 <= age < self.policy["decision_budget_ms"]:
            if (
                self.policy["mode"] == "observe" or self._startup_retry() or not self.fresh_frame_seen
            ) and self.clock() - self.started <= 5.0:
                return None
            raise ComputeError("navigation_frame_expired")
        return frame, age

    def _frame_arrived(self, frame):
        if not frame or (self.last_frame is not None and frame["captured_at"] <= self.last_frame[1]):
            limit = (
                5.0
                if not self.fresh_frame_seen or self.policy["mode"] == "observe"
                else self.policy["decision_budget_ms"] / 1000
            )
            if self.clock() - self.started > limit:
                raise ComputeError("navigation_camera_unavailable")
            return False
        return True

    def _frame_metadata(self, age):
        self.fresh_frame_seen = True
        self.started = self.clock()
        captured = self.clock() - age / 1000
        self.sequence += 1
        frame_id = hashlib.sha256(str(self.last_frame).encode()).hexdigest()
        meta = {
            "protocol_version": 1,
            "run_id": self.run_id,
            "frame_id": frame_id,
            "sequence": self.sequence,
            "config_revision": self.policy["revision"],
            "age_ms": float(age),
            "deadline_ms": self.policy["decision_budget_ms"],
            **{k: self.policy[k] for k in ("mode", "corridor", "verified", "calibration_id", "model_sha256")},
        }
        meta["perception"] = self.policy["perception"]
        if self.policy["mode"] == "drive" and self.lease.journey is not None:
            meta["journey"] = dict(self.lease.journey.context)
        if self.policy.get("avoidance", {}).get("enabled"):
            motion_phase = "ready"
            if self.turn_capture_after is not None and captured <= self.turn_capture_after:
                motion_phase = (
                    "steer_wait" if self.policy["avoidance"].get("protocol_version", 2) == 3 else "turn_settling"
                )
            meta.update(
                protocol_version=self.policy["avoidance"].get("protocol_version", 2),
                avoidance=self.policy["avoidance"],
                motion_phase=motion_phase,
            )
        return captured, meta

    def _request_decision(self, meta, frame, captured):
        request_started = self.clock()
        try:
            decision = self.request(meta, frame["data"], frame["content_type"])
        except (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError) as exc:
            if not self._retry_observation(exc):
                raise
            detail = {}
            if isinstance(exc, urllib.error.HTTPError):
                from apps.compute.stream_prepare import http_error_code

                detail = {"http_status": exc.code, "transport_error": http_error_code(exc)}
            reason = detail.get("transport_error")
            if reason is None or reason.startswith("http_"):
                reason = "vision_observation_transport_retry"
            self.last_result = {
                "state": "unknown",
                "action": "stop",
                "vision_action": "stop",
                "reason": reason,
                "motion_reason": reason,
                **detail,
                **({"source": dict(frame["data"])} if isinstance(frame["data"], dict) else {}),
                "clear_count": 0,
                "valid_for_ms": 0,
                **{k: meta[k] for k in ("protocol_version", "run_id", "frame_id", "sequence", "config_revision")},
            }
            self.request_roundtrip_ms = round((self.clock() - request_started) * 1000, 2)
            self.response_age_ms = round((self.clock() - captured) * 1000, 2)
            self._status(self.last_result)
            self.closed.wait(0.2)
            return False, None
        self.request_roundtrip_ms = round((self.clock() - request_started) * 1000, 2)
        self.response_age_ms = round((self.clock() - captured) * 1000, 2)
        self.last_result = decision
        return True, decision

    def _apply_decision(self, decision, meta, captured):
        frame_id = meta["frame_id"]
        if self._startup_reply_expired(decision, meta, captured):
            self.last_result = {
                **decision,
                "state": "unknown",
                "action": "stop",
                "vision_action": "stop",
                "reason": "navigation_startup_waiting_fresh_frame",
                "motion_reason": "navigation_startup_waiting_fresh_frame",
                "valid_for_ms": 0,
            }
            self._status(self.last_result)
            return False, self.last_result
        if (
            self.turn_capture_after is not None
            and captured <= self.turn_capture_after
            and decision.get("action") != "stop"
        ):
            # A stale orientation can never issue forward or a second turn.
            decision = {
                **decision,
                "action": "stop",
                "state": "clear",
                "motion_reason": "avoidance_turn_settling",
            }
            self.last_result = decision
        admitted, decision = self._qualify_decision(decision, frame_id, captured)
        if not admitted:
            return False, decision
        self._timed("decision_apply_ms", self.lease.accept, decision, frame_id, self.sequence, captured)
        if not self.lease.latched and self.lease.reason == "awaiting_fresh_decision":
            # Keep the image verdict, but report the actual ZERO sent
            # to Pi while waiting for a usable fresh motion permit.
            decision = {**decision, "action": "stop", "motion_reason": self.lease.reason}
            self.last_result = decision
        return True, decision

    def _qualify_decision(self, decision, frame_id, captured):
        if self.operator_lifecycle.enabled:
            # Generation can change while remote inference is in flight.
            generation = self.generation
            if not self._authority() or generation != self.generation:
                self._status(None)
                return False, self.last_result
            decision = self.operator_lifecycle.evidence(decision, frame_id, self.sequence, captured)
            self.last_result = decision
            if self.operator_lifecycle.qualification.count < 3:
                self._status(decision)
                return False, self.last_result
        return True, decision

    def _finish_cycle(self, decision):
        self._status(decision)
        if self.lease.latched:
            if self.operator_lifecycle.enabled:
                self._authority()
            else:
                self.closed.set()
        if self.policy["mode"] == "observe":
            self.closed.wait(0.01)
