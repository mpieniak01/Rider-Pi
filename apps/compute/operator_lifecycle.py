"""Warm perception session layered on the existing single navigation runner."""

from __future__ import annotations

import uuid

from apps.compute.client import ComputeError
from apps.compute.decision_lease import DecisionLease
from apps.compute.journey import JourneyProgress
from apps.compute.qualification import Qualification
from apps.safety.intent import write_intent_status


class OperatorLifecycle:
    def __init__(self, runner):
        self.runner = runner
        self.enabled = False
        self.journey_id = None
        self.panel_id = None
        self.claim = None
        self.operation = None
        self.pause_reason = None
        self.qualification = None
        self.authorized = False
        self.qualified = False
        self.last_claim = float("-inf")

    def _qualification(self):
        runner = self.runner
        ground = (
            runner.policy.get("avoidance", {}).get("enabled")
            and runner.policy["avoidance"].get("protocol_version") == 3
            and runner.policy["avoidance"].get("geometry", {}).get("mode") == "ground"
        )
        return Qualification(
            runner.policy,
            runner.run_id,
            runner.clock(),
            validate_evidence=runner.lease._ground_evidence if ground else None,
        )

    def admit(self, safety, intent):
        control = safety.get("operator_control") or {}
        panel = (safety.get("panel_control") or {}).get("holder")
        if control.get("version") == 1 and control.get("state") in {"qualifying", "active"} and panel and intent:
            self.enabled = True
            self.panel_id = panel
            self.claim = dict(intent)
            self.operation = control.get("operation_id")
            self.qualification = self._qualification()
            self.authorized = True
            if safety.get("arming_mode") == "journey":
                journey = safety.get("journey") or {}
                if (
                    type(safety.get("navigation_journey_version")) is not int
                    or safety["navigation_journey_version"] != 1
                    or journey.get("active") is not True
                ):
                    raise ComputeError("navigation_journey_update_required")
                identity = {"version": 1, "id": journey.get("id"), "maneuver_epoch": 0}
                self.runner.lease.journey = JourneyProgress(identity, self.runner.clock)
                self.journey_id = identity["id"]
            epoch = self.runner.run_id
            generation = safety.get("generation")
            self.runner.lease.stop = lambda: self.runner.stop(expected_run_id=epoch, expected_generation=generation)
            self.runner.lease.drive = lambda *args, **kwargs: self.runner.drive(*args, expected_run_id=epoch, **kwargs)
            self.runner.lease.pause = lambda *args: self.runner.pause(*args, expected_run_id=epoch)
            self.runner.lease.turn = lambda *args: self.runner.turn(*args, expected_run_id=epoch)
            self.runner.lease.steer = lambda *args: self.runner.steer(*args, expected_run_id=epoch)

    def sync(self, safety):
        runner = self.runner
        control = safety.get("operator_control") or {}
        authorized = (
            safety.get("can_move") is True
            and safety.get("owner") == "navigation"
            and safety.get("state") == "ARMED"
            and (safety.get("panel_control") or {}).get("holder") == self.panel_id
            and control.get("version") == 1
            and control.get("state") in {"qualifying", "active"}
            and isinstance(control.get("operation_id"), str)
        )
        if self.journey_id is not None and (
            not authorized
            or runner.generation != safety.get("generation")
            or control.get("operation_id") != self.operation
            or safety.get("arming_mode") != "journey"
            or (safety.get("journey") or {}).get("id") != self.journey_id
            or (safety.get("journey") or {}).get("active") is not True
        ):
            # Terminal mission identity never becomes a warm/resumable trial.
            # Raising is safe even inside a DecisionLease callback holding its lock.
            raise ComputeError((safety.get("journey") or {}).get("reason") or "navigation_authority_lost")
        if self.journey_id is not None:
            runner._check_executor_support(safety)
            runner._check_rejected_acks(safety)
            runner._check_pending_acks(safety)
            runner._check_navigation_intent(safety, runner._live_intent(safety))
        changed = runner.generation != safety.get("generation") or self.authorized != authorized
        if changed:
            self.pause_reason = None if authorized else safety.get("reason") or control.get("reason")
            # The previous producer can no longer touch the newer generation.
            # Replace local freshness state; never reuse an old GO or clear count.
            runner.generation = safety.get("generation")
            self.operation = control.get("operation_id")
            runner.policy = {**runner.saved_policy, "mode": "drive" if authorized else "observe"}
            runner.run_id = uuid.uuid4().hex
            runner.sequence = 0
            runner.motion_sequence = safety.get("last_seq", -1)
            runner.pending_motion_acks.clear()
            runner.motion_started = False
            runner.motion_failure = None
            runner.turn_capture_after = None
            runner.startup_deadline = runner.clock() + 5
            self.qualification = self._qualification()
            self.qualified = False
            runner.lease = DecisionLease(
                runner.policy,
                runner.run_id,
                lambda *args, epoch=runner.run_id, **kwargs: runner.drive(*args, expected_run_id=epoch, **kwargs),
                lambda epoch=runner.run_id, generation=runner.generation: runner.stop(
                    expected_run_id=epoch, expected_generation=generation
                ),
                runner.clock,
                pause=lambda *args, epoch=runner.run_id: runner.pause(*args, expected_run_id=epoch),
                feedback_wait=authorized,
                turn=lambda *args, epoch=runner.run_id: runner.turn(*args, expected_run_id=epoch),
                steer=lambda *args, epoch=runner.run_id: runner.steer(*args, expected_run_id=epoch),
            )
        self.authorized = authorized
        if runner.clock() - self.last_claim >= 0.2:
            write_intent_status(
                "rider-venom-navigation.service",
                self.claim,
                active=True,
                data_ready=runner.fresh_frame_seen,
                navigation_ready=runner.fresh_frame_seen,
                operator_control_version=1,
            )
            self.last_claim = runner.clock()
        return authorized

    def evidence(self, decision, frame_id, sequence, captured):
        if not self.enabled or not self.authorized:
            return decision
        journey = self.runner.lease.journey
        if journey is not None and not journey.validate_reply(decision):
            self.runner.lease.halt("navigation_journey_identity_mismatch")
            raise ComputeError("navigation_journey_identity_mismatch")
        if self.qualified:
            if self.qualification.source_context(decision) == self.qualification.source:
                return decision
            self.qualified = False
            self.qualification.count = 0
        ready = self.qualification.accept(decision, frame_id, sequence, captured, self.runner.clock())
        if ready:
            self.qualified = True
            return {**decision, "clear_count": 3}
        # Qualification is observation only. Do not feed a stale/invalid frame to
        # DecisionLease: the separate executor consent and watchdog stay bounded.
        return {**decision, "action": "stop", "motion_reason": "awaiting_fresh_qualification"}

    def status(self):
        if not self.enabled:
            return {}
        count = self.qualification.count if self.qualification else 0
        return {
            "operator_control_version": 1,
            "qualification_count": count,
            "operation_id": self.operation,
            "operator_pause_reason": self.pause_reason,
            **({"journey": self.runner.lease.journey.snapshot()} if self.journey_id is not None else {}),
        }
