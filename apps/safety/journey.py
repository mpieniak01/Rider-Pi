"""Executor-owned journey consent; only accepted fresh motor goals renew it."""

from __future__ import annotations

import math

BOOTSTRAP_S = 5.0


def validate_arm(command, owner, context):
    mode = command.get("arming_mode", "timed")
    if mode != "journey":
        if "journey_version" in command or "journey_id" in command:
            raise ValueError("navigation_journey_invalid")
        return
    if (
        command.get("source") != "manual"
        or context != "panel"
        or owner != "navigation"
        or type(command.get("journey_version")) is not int
        or command["journey_version"] != 1
        or type(command.get("operator_control_version")) is not int
        or command["operator_control_version"] != 1
        or not isinstance(command.get("journey_id"), str)
        or not 1 <= len(command["journey_id"]) <= 128
        or any(char.isspace() for char in command["journey_id"])
        or not isinstance(command.get("panel_id"), str)
        or not 1 <= len(command["panel_id"].strip()) <= 128
        or "lease_s" in command
    ):
        raise ValueError("navigation_journey_invalid")


class JourneyConsent:
    def __init__(self, gate):
        self.gate = gate
        self.id = None
        self.active = False
        self.started = None
        self.ended = None
        self.state = "stopped"
        self.reason = "no_navigation_journey"

    def arm(self, command):
        if command.get("arming_mode") != "journey":
            return
        self.id = command["journey_id"]
        self.active = True
        self.started = self.gate.clock()
        self.ended = None
        self.state = "qualifying"
        self.reason = "awaiting_fresh_qualification"
        self.gate.lease_deadline = self.started + BOOTSTRAP_S

    def end(self, reason):
        if self.active:
            self.active = False
            self.ended = self.gate.clock()
            self.state = (
                "stopped" if reason in {"operator_stop", "operator_intervention", "navigation_stopped"} else "failed"
            )
            self.reason = reason

    def validate_goal(self, command):
        if self.gate.arming_mode != "journey":
            return
        if (
            not self.active
            or command.get("action") not in {"move", "turn"}
            or command.get("source") != "navigation"
            or command.get("journey_id") != self.id
            or type(command.get("journey_version")) is not int
            or command["journey_version"] != 1
            or any(
                command.get(key) is None
                for key in ("decision_deadline_monotonic", "decision_feedback_deadline_monotonic")
            )
        ):
            raise ValueError("navigation_journey_goal_invalid")

    def accepted_goal(self, command, feedback):
        if self.gate.arming_mode != "journey":
            return
        self.validate_goal(command)
        if (
            type(feedback) not in (int, float)
            or not math.isfinite(feedback)
            or not 0 < feedback - self.gate.clock() <= 0.5
        ):
            raise ValueError("decision_feedback_deadline_expired")
        # Called only after the controller accepts the independently bounded goal.
        self.gate.lease_deadline = feedback
        self.state = "active"
        self.reason = "fresh_navigation_feedback"

    def snapshot(self):
        endpoint = self.gate.clock() if self.active else self.ended
        return {
            "version": 1,
            "id": self.id,
            "active": self.active,
            "state": self.state,
            "reason": self.reason,
            "elapsed_s": round(max(0.0, endpoint - self.started), 3)
            if endpoint is not None and self.started is not None
            else 0.0,
        }
