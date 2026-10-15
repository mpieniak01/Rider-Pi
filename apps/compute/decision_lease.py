"""Bounded motor permits; fresh replies never revive a terminally stopped run."""

from __future__ import annotations

import math
import threading
import time


class DecisionLease:
    def __init__(self, config, run_id, drive, stop, clock=time.monotonic, *, pause=None, feedback_wait=False):
        self.config = dict(config)
        self.run_id = run_id
        self.drive, self.stop, self.clock = drive, stop, clock
        self.pause = pause
        self.feedback_wait = feedback_wait and pause is not None
        self.feedback_deadline = None
        self.lock = threading.Lock()
        self.last_seq = -1
        self.deadline = None
        self.latched = False
        self.moving = False
        self.reason = "waiting_for_decision"

    def halt(self, reason):
        with self.lock:
            self._halt(reason)

    def _halt(self, reason):
        if self.latched:
            self.stop()
            return
        self.latched = True
        self.reason = reason
        self.deadline = None
        self.feedback_deadline = None
        self.moving = False
        self.stop()

    def _wait_for_feedback(self, now):
        if not self.feedback_wait or self.feedback_deadline is None or now >= self.feedback_deadline:
            return False
        # The executor already zeros the bounded command at its deadline/pulse
        # end. Clearing this permit never emits or renews a motion command.
        self.deadline = None
        self.moving = False
        self.reason = "awaiting_fresh_decision"
        return True

    def tick(self):
        with self.lock:
            now = self.clock()
            if self.feedback_deadline is not None and now >= self.feedback_deadline:
                self._halt("decision_timeout")
            elif self.deadline is not None and now >= self.deadline and not self._wait_for_feedback(now):
                self._halt("decision_timeout")
            return not self.latched

    def accept(self, decision, frame_id, sequence, captured_monotonic):
        with self.lock:
            if self.latched:
                return False
            now = self.clock()
            if self.feedback_deadline is not None and now >= self.feedback_deadline:
                self._halt("decision_timeout")
                return False
            if self.deadline is not None and now >= self.deadline and not self._wait_for_feedback(now):
                self._halt("decision_timeout")
                return False
            identity = {
                "protocol_version": 1,
                "run_id": self.run_id,
                "frame_id": frame_id,
                "sequence": sequence,
                "config_revision": self.config["revision"],
            }
            remaining = self.config["decision_budget_ms"] / 1000 - (now - captured_monotonic)
            if (
                not isinstance(decision, dict)
                or any(decision.get(k) != v for k, v in identity.items())
                or any(type(decision.get(k)) is not int for k in ("protocol_version", "sequence", "config_revision"))
                or not math.isfinite(captured_monotonic)
                or now < captured_monotonic
                or type(sequence) is not int
                or sequence <= self.last_seq
                or remaining <= 0
            ):
                self._halt("decision_invalid_or_expired")
                return False
            valid = decision.get("valid_for_ms")
            if type(valid) is not int or not 0 < valid <= 200:
                self._halt("decision_invalid_or_expired")
                return False
            if decision.get("action") not in {"go", "stop"}:
                self._halt("decision_invalid_action")
                return False
            self.last_seq = sequence
            self.reason = str(decision.get("reason", "unknown"))[:128]
            if decision["action"] == "stop":
                if self.pause is None:
                    # Older callers without scoped zero output retain terminal STOP.
                    if self.moving or decision.get("state") != "clear":
                        self._halt(self.reason)
                    return False
                if decision.get("state") not in {"clear", "obstacle", "unknown"}:
                    self._halt("decision_invalid_state")
                    return False
                if decision.get("state") == "unknown" and self.reason not in {
                    "vision_image_quality",
                    "vision_low_confidence",
                    "vision_floor_uncertainty",
                    "depth_ground_orientation",
                }:
                    self._halt(self.reason)
                    return False
                permit = min(remaining, valid / 1000)
                duration = min(permit, self.config["max_motion_ms"] / 1000)
                if duration < 0.05:
                    self._halt("decision_budget_exhausted")
                    return False
                # A fresh visual STOP renews only a zero goal in the original ARM.
                # The watchdog also expires paused runs; old GO cannot revive them.
                if self.feedback_wait:
                    self.feedback_deadline = now + self.config["decision_budget_ms"] / 1000
                self.deadline = now + permit
                self.moving = False
                self.reason = str(decision.get("motion_reason", self.reason))[:128]
                try:
                    self.pause(duration)
                except Exception:
                    self._halt("motion_submission_failed")
                    raise
                return False
            if (
                decision.get("state") != "clear"
                or type(decision.get("clear_count")) is not int
                or decision["clear_count"] < 3
                or self.config["mode"] != "drive"
                or self.config["verified"] is not True
                or decision.get("model_sha256") != self.config["model_sha256"]
            ):
                self._halt("decision_not_authorized")
                return False
            permit = min(remaining, valid / 1000)
            duration = min(permit, self.config["max_motion_ms"] / 1000)
            if duration < 0.05:
                self._halt("decision_budget_exhausted")
                return False
            # Pulse length is enforced by the executor. The lease tracks freshness,
            # so a fresh reply after a completed pulse can renew the same run.
            if self.feedback_wait:
                self.feedback_deadline = now + self.config["decision_budget_ms"] / 1000
            self.deadline = now + permit
            self.moving = True
            try:
                self.drive(self.config["speed"], duration)
            except Exception:
                self._halt("motion_submission_failed")
                raise
            return True
