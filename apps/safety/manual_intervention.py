"""A fresh direction gesture grants manual authority; scoped releases grant none."""

from __future__ import annotations

from collections import deque


def validate(command):
    if "operator_intervention_version" not in command:
        return
    if (
        type(command["operator_intervention_version"]) is not int
        or command["operator_intervention_version"] != 1
        or command.get("action") not in {"move", "turn"}
        or command.get("intervene") is not True
        or command.get("source") != "manual"
        or command.get("execution_context") != "panel"
        or not isinstance(command.get("panel_id"), str)
        or not 1 <= len(command["panel_id"].strip()) <= 128
        or command.get("device_settings") is not True
    ):
        raise ValueError("operator_intervention_invalid")
    if command.get("mode") == "release":
        if not isinstance(command.get("supersedes_operation_id"), str) or not command["supersedes_operation_id"]:
            raise ValueError("operator_intervention_target_required")
        return
    if (
        command.get("operator_consent") is not True
        or command.get("owner") != "manual"
        or command.get("arming_mode") != "operator"
        or "lease_s" in command
        or not isinstance(command.get("operator_plan"), str)
        or not 1 <= len(command["operator_plan"].strip()) <= 512
    ):
        raise ValueError("operator_intervention_consent_required")


class ManualIntervention:
    def __init__(self, gate):
        self.gate = gate
        self.operation = None
        self.cancelled = deque(maxlen=64)

    @staticmethod
    def requested(command):
        return "operator_intervention_version" in command

    def priority_sequence(self, command):
        if not self.requested(command):
            return None
        validate(command)
        gate = self.gate
        target = command.get("supersedes_operation_id")
        if command.get("mode") == "release":
            operation = self.operation
            if (
                operation is not None
                and target == operation["request_id"]
                and command.get("panel_id") == operation["panel_id"]
                and command.get("generation") in {operation["origin"], operation["generation"]}
                and gate.generation == operation["generation"]
                and gate.panel_id == operation["panel_id"]
            ):
                return -1
            if self._navigation_target(command):
                return -1
        elif (
            gate.owner == "navigation"
            and target in {gate.operator_control.operation_id, gate.journey.id}
            and target is not None
            and command.get("generation")
            in {
                gate.generation,
                gate.operator_control.origin_generation,
                gate.operator_control.preparation_origin_generation,
            }
            and (command.get("generation") == gate.generation or command.get("panel_id") == gate.panel_id)
        ):
            return -1
        return None

    def _navigation_target(self, command):
        gate = self.gate
        target = command.get("supersedes_navigation_operation_id")
        return (
            gate.owner == "navigation"
            and gate.state == "ARMED"
            and command.get("generation")
            in {
                gate.generation,
                gate.operator_control.origin_generation,
                gate.operator_control.preparation_origin_generation,
            }
            and command.get("panel_id") == gate.panel_id
            and isinstance(target, str)
            and target in {gate.operator_control.operation_id, gate.journey.id}
        )

    def transfer(self, command):
        validate(command)
        gate = self.gate
        identity = (command["panel_id"], command["generation"], command["request_id"])
        if identity in self.cancelled:
            raise ValueError("operator_intervention_cancelled")
        # Permission is new explicit manual consent, never converted old GO.
        gate._arming_parameters(command, "panel")
        origin = command["generation"]
        gate.disarm("operator_intervention")
        gate._authorize_arm(command, "panel")
        self.operation = {
            "request_id": command["request_id"],
            "panel_id": command["panel_id"],
            "origin": origin,
            "generation": gate.generation,
        }
        gate.reason = "operator_intervention"
        # The status can arrive before its ACK. Identify the exact own transfer
        # without enabling the old timed navigation-resume lifecycle.
        gate.operator_control.state = "paused"
        gate.operator_control.operation_id = command["request_id"]
        gate.operator_control.reason = "operator_intervention"

    def supersede(self, command):
        """A newer ordinary manual goal owns output in this same generation."""
        operation = self.operation
        if (
            operation is not None
            and command.get("source") == "manual"
            and command.get("action") in {"move", "turn"}
            and command.get("generation") == operation["generation"]
            and command.get("request_id") != operation["request_id"]
        ):
            self.operation = None
            self.gate.operator_control.operation_id = command["request_id"]
            self.gate.operator_control.reason = "manual_goal_superseded_intervention"

    def release(self, command):
        validate(command)
        gate = self.gate
        gate._validate_envelope(command)
        target = command["supersedes_operation_id"]
        identity = (command["panel_id"], command["generation"], target)
        if identity in self.cancelled:
            return False  # Replayed release cannot zero a newer ordinary manual goal.
        operation = self.operation
        matching = (
            operation is not None
            and target == operation["request_id"]
            and command.get("panel_id") == operation["panel_id"]
            and gate.generation == operation["generation"]
            and gate.panel_id == operation["panel_id"]
            and command.get("generation") in {operation["origin"], operation["generation"]}
        )
        if not matching and command.get("generation") != gate.generation and not self._navigation_target(command):
            raise ValueError("operator_intervention_stale")
        self.cancelled.append(identity)
        if matching:
            self.cancelled.append((operation["panel_id"], operation["origin"], target))
            self.cancelled.append((operation["panel_id"], operation["generation"], target))
        if not matching and (
            self._navigation_target(command)
            or gate.state == "DISARMED"
            and command.get("generation") == gate.generation
        ):
            # Cancel-only priority STOP invalidates any unarmed preparation in
            # this exact origin. It never re-arms, and cannot revoke a new owner.
            gate.disarm("operator_intervention_cancelled")
            return True
        if matching:
            gate.motion_not_before = gate.wall_clock()
            gate.last_seq = max(gate.last_seq, command["seq"])
            gate.invalidate_agent(manual=True)
        return matching
