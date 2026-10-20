"""Executor-owned warm operator authority; never starts a service or extends consent."""

from __future__ import annotations

import uuid

ACTIONS = frozenset({"navigation_pause", "navigation_resume"})


class OperatorControl:
    def __init__(self, gate):
        self.gate = gate
        self.origin_generation = None
        self.preparation_origin_generation = None
        self.origin_sequence = -1
        self.enabled = False
        self.state = "idle"
        self.operation_id = None
        self.reason = "no_navigation_session"

    def reset(self, reason):
        self.origin_generation = None
        self.preparation_origin_generation = None
        self.origin_sequence = -1
        self.enabled = False
        self.state = "idle"
        self.operation_id = None
        self.reason = reason

    def arm(self, command):
        if command.get("operator_control_version") == 1:
            self.enabled = True
            self.state = "qualifying" if self.gate.owner == "navigation" else "paused"
            self.operation_id = command["request_id"]
            self.origin_generation = self.gate.generation
            self.preparation_origin_generation = command.get("operator_origin_generation")
            self.origin_sequence = command["seq"]
            self.reason = "awaiting_fresh_qualification" if self.state == "qualifying" else "operator_pause"

    def validate_arm(self, command, owner, context):
        if "operator_control_version" not in command:
            return
        if (
            type(command["operator_control_version"]) is not int
            or command["operator_control_version"] != 1
            or context != "panel"
            or owner != "navigation"
            or (
                command.get("arming_mode", "timed") != "journey"
                and (
                    command.get("arming_mode", "timed") != "timed"
                    or type(command.get("lease_s")) not in (int, float)
                    or not 0 < command["lease_s"] <= 10
                )
            )
            or not isinstance(command.get("panel_id"), str)
            or not command["panel_id"].strip()
        ):
            raise ValueError("operator_control_invalid")

    def priority_sequence(self, command):
        gate = self.gate
        target = command.get("supersedes_operation_id")
        priority = command.get("action") == "navigation_pause" or (
            command.get("action") in {"move", "turn"} and command.get("intervene") is True
        )
        if (
            self.enabled
            and gate.state == "ARMED"
            and gate.owner == "navigation"
            and self.state in {"qualifying", "active"}
            and priority
            and isinstance(target, str)
            and target == self.operation_id
            and command.get("source") == "manual"
            and command.get("execution_context") == "panel"
            and gate.panel_id is not None
            and command.get("panel_id") == gate.panel_id
            and isinstance(command.get("generation"), str)
            and command.get("generation") in {gate.generation, self.origin_generation}
        ):
            return self.origin_sequence
        return None

    def _validate_transfer(self, command):
        """Validate panel ownership and remaining consent before changing navigation authority."""
        gate = self.gate
        if not self.enabled:
            raise ValueError("operator_control_not_available")
        if not gate.can_actuate():
            raise ValueError("estop_latched" if gate.state == "ESTOP" else "motion_disarmed")
        if command.get("source") != "manual" or command.get("execution_context") != "panel":
            raise ValueError("operator_panel_required")
        if gate.panel_id is None or command.get("panel_id") != gate.panel_id:
            raise ValueError("panel_owner_mismatch")
        if gate.owner not in {"manual", "navigation"}:
            raise ValueError("owner_mismatch")
        resume = command.get("action") == "navigation_resume"
        if gate.arming_mode == "journey":
            if resume:
                raise ValueError("navigation_journey_new_start_required")
            return False
        if gate.arming_mode != "timed" or not 0 < gate.lease_deadline - gate.clock() <= 10:
            raise ValueError("navigation_timed_consent_required")
        if resume and self.state in {"qualifying", "active"}:
            raise ValueError("navigation_already_active")
        return resume

    def transfer(self, command):
        resume = self._validate_transfer(command)
        gate = self.gate
        if gate.arming_mode == "journey":
            gate.disarm("operator_intervention")
            return
        # The single executor serializes this change with its output. Preserve
        # consent exactly; timed leases cannot become operator leases here.
        self.origin_generation = gate.generation if resume else None
        self.origin_sequence = command["seq"] if resume else -1
        gate.generation = uuid.uuid4().hex
        gate.last_seq = command["seq"]
        gate.motion_not_before = gate.wall_clock()
        gate.owner = "navigation" if resume else "manual"
        gate.invalidate_agent(manual=not resume)
        self.state = "qualifying" if resume else "paused"
        self.operation_id = command["request_id"]
        self.reason = "awaiting_fresh_qualification" if resume else "operator_intervention"
        gate.reason = self.reason

    def validate_navigation(self, command):
        if self.enabled and command.get("source") == "navigation":
            if command.get("operator_operation_id") != self.operation_id:
                raise ValueError("navigation_operation_stale")

    def activated(self, command):
        if self.enabled and command.get("source") == "navigation":
            self.state = "active"
            self.reason = "fresh_qualification_accepted"

    def snapshot(self):
        return {
            "version": 1,
            "state": self.state,
            "operation_id": self.operation_id,
            "generation": self.gate.generation,
            "reason": self.reason,
        }
