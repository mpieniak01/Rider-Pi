"""One bounded navigation capture/request/decision cycle."""

import hashlib
import socket
import time
import urllib.error

from apps.compute.client import ComputeError

from .http_budget import CaptureBudgetExpired


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
        meta["perception"] = dict(self.policy["perception"])
        if not meta["perception"].get("semantic_models"):
            meta["perception"].pop("semantic_models", None)
        from services.navigation_behavior import active

        if active(self.policy):
            meta["behavior"] = self.policy["behavior"]
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
        requested_lease, requested_generation = self.lease, self.generation
        self.request_roundtrip_ms = self.response_age_ms = None
        self.request_attempt = {
            "run_id": meta.get("run_id"),
            "sequence": meta.get("sequence"),
            "state": "pending",
            "started_monotonic": request_started,
            "captured_monotonic": captured,
        }
        try:
            decision = self.request(meta, frame["data"], frame["content_type"])
        except Exception as exc:
            failed_at = time.time()
            self._finish_request("failed", type(exc).__name__)
            if self._operator_stopped_request(exc, meta, failed_at, requested_lease, requested_generation):
                return False, None
            bounded_retry = self._retry_capture_budget(exc, meta)
            network_error = isinstance(exc, (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError))
            if not bounded_retry and (not network_error or not self._retry_observation(exc)):
                raise
            self._record_retry_result(exc, meta, frame, bounded_retry)
            if not bounded_retry:
                self.closed.wait(0.2)
            return False, None
        self._finish_request("completed")
        self._check_model_reply(decision, meta)
        self.last_result = decision
        return True, decision

    def _operator_stopped_request(self, error, meta, failed_at, lease, generation):
        if not isinstance(error, urllib.error.HTTPError) or error.code != 409:
            return False
        from .stream_prepare import http_error_code

        if http_error_code(error) != "stale_device_session":
            return False
        from .navigation import read_status

        return self.operator_lifecycle.retire_stopped_request(meta, read_status(), failed_at, lease, generation)

    def _record_retry_result(self, error, meta, frame, bounded_retry):
        detail = {}
        if isinstance(error, urllib.error.HTTPError):
            from apps.compute.stream_prepare import http_error_code

            detail = {"http_status": error.code, "transport_error": http_error_code(error)}
        reason = "navigation_capture_budget_expired" if bounded_retry else detail.get("transport_error")
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
        self._status(self.last_result)

    def _request_diagnostics(self):
        attempt = dict(self.request_attempt or {})
        if attempt.get("state") == "pending":
            attempt["elapsed_ms"] = round((self.clock() - attempt["started_monotonic"]) * 1000, 2)
            attempt["capture_age_ms"] = round((self.clock() - attempt["captured_monotonic"]) * 1000, 2)
        return attempt

    def _finish_request(self, state, error=None):
        self.request_roundtrip_ms = round((self.clock() - self.request_attempt["started_monotonic"]) * 1000, 2)
        self.response_age_ms = round((self.clock() - self.request_attempt["captured_monotonic"]) * 1000, 2)
        self.request_attempt = {
            **self.request_attempt,
            "state": state,
            "error": error,
            "elapsed_ms": self.request_roundtrip_ms,
            "capture_age_ms": self.response_age_ms,
        }

    def _retry_capture_budget(self, error, meta):
        if self.policy["mode"] != "drive":
            return False
        transient = isinstance(error, CaptureBudgetExpired)
        if isinstance(error, urllib.error.HTTPError):
            from .stream_prepare import http_error_code

            transient = error.code in {409, 429} and http_error_code(error) in {
                "vision_frame_expired",
                "stream_frame_unavailable",
                "vision_busy",
            }
        if not transient:
            return False
        lease = self.lease
        if not self._authority() or self.run_id != meta.get("run_id") or self.lease is not lease:
            return False
        if self._retry_startup_capture(lease):
            return True
        return lease.journey is not None and lease.await_fresh_capture()

    def _retry_startup_capture(self, lease):
        # Before the first permit there is no feedback window to wait inside.
        # Keep the existing startup clock and authority, never renew either.
        with self.operator_lifecycle.lock:
            if (
                self.lease is not lease
                or lease.latched
                or self.closed.is_set()
                or lease.deadline is not None
                or lease.feedback_deadline is not None
                or not self._startup_retry()
            ):
                return False
            if self.operator_lifecycle.qualification is not None:
                # Evidence before a failed capture is not a consecutive series.
                # Preserve anti-replay identities while requiring three new frames.
                self.operator_lifecycle.qualification.count = 0
                self.operator_lifecycle.qualified = False
            return True

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
            self._check_model_reply(decision, meta)
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

    def _check_model_reply(self, decision, meta):
        from services.navigation_behavior import reply_valid

        if not isinstance(decision, dict) or not reply_valid(self.policy, decision):
            raise ComputeError("navigation_behavior_identity_mismatch")
        perception = self.policy.get("perception", {})
        if not perception.get("model_id"):
            return  # Legacy peers keep the original v1/v2/v3 wire contract.
        expected = {key: meta[key] for key in ("protocol_version", "run_id", "frame_id", "sequence", "config_revision")}
        expected.update(
            model_id=perception["model_id"],
            artifact_sha256=perception["artifact_sha256"],
        )
        if (
            not isinstance(decision, dict)
            or any(decision.get(key) != value for key, value in expected.items())
            or any(type(decision.get(key)) is not int for key in ("protocol_version", "sequence", "config_revision"))
        ):
            raise ComputeError("navigation_model_identity_mismatch")
