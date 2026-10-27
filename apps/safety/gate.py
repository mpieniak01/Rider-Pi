"""One consent lease for every actuator, owned by the motion executor."""

from __future__ import annotations

import logging
import math
import os
import time
import uuid
from collections.abc import Callable

from apps.motion.limits import MAX_DURATION_S as MAX_DURATION_S
from apps.safety import estop
from apps.safety.journey import JourneyConsent, validate_arm as validate_journey_arm
from apps.safety.manual_intervention import ManualIntervention, validate as validate_intervention
from apps.safety.operator_control import ACTIONS as OPERATOR_ACTIONS, OperatorControl
from common.agent_control import MANUAL_AGENT_GRACE_S, verify_command

OWNERS = frozenset({"manual", "follow_me", "navigation"})
ACTUATORS = frozenset({"move", "turn", "balance", "height", "action", "stabilization"})
MAX_LEASE_S = 30.0
MAX_TTL_MS = 500.0


def finite_number(value, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(name)
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(name) from exc
    if not math.isfinite(result):
        raise ValueError(name)
    return result


class MotionGate:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        blocked: Callable[[], bool] | None = None,
    ):
        self.clock = clock
        self.wall_clock = wall_clock
        self.blocked = blocked or estop.external_estop
        self.state = "DISARMED"
        self.owner = None
        self.execution_context = None
        self.panel_id = None
        self.generation = uuid.uuid4().hex
        self.last_seq = -1
        self.motion_not_before = None
        self.lease_deadline = 0.0
        self.arming_mode = "timed"
        self.reason = "startup_disarmed"
        self.plan = None
        self.persistence_error = None
        self.agent_epoch = uuid.uuid4().hex
        self.agent_last_seq = -1
        self.agent_intents = []
        self.manual_grace_until = 0.0
        self.operator_control = OperatorControl(self)
        self.manual_intervention = ManualIntervention(self)
        self.journey = JourneyConsent(self)
        self.poll()

    def _invalidate(self, state: str, reason: str) -> None:
        logging.getLogger("motion.permission").info(
            "permission %s -> %s reason=%s generation=%s", self.state, state, reason, self.generation
        )
        self.journey.end(reason)
        self.state = state
        self.reason = reason
        self.owner = None
        self.execution_context = None
        self.panel_id = None
        self.plan = None
        self.lease_deadline = 0.0
        self.arming_mode = "timed"
        self.generation = uuid.uuid4().hex
        self.last_seq = -1
        self.invalidate_agent()
        self.operator_control.reset(reason)

    def invalidate_agent(self, *, manual=False) -> None:
        self.agent_epoch = uuid.uuid4().hex
        self.agent_last_seq = -1
        self.agent_intents = []
        self.manual_grace_until = self.clock() + MANUAL_AGENT_GRACE_S if manual else 0.0

    def cancel_motion(self, reason: str) -> None:
        """Drop old intents without revoking an operator-controlled session."""
        self.motion_not_before = self.wall_clock()
        self.invalidate_agent()
        if self.arming_mode != "operator":
            self.disarm(reason)

    def disarm(self, reason: str = "operator_stop") -> None:
        self._invalidate("ESTOP" if self.state == "ESTOP" else "DISARMED", reason)

    def latch_estop(self, reason: str = "operator_estop", *, persist: bool = True) -> None:
        if self.state != "ESTOP":
            self._invalidate("ESTOP", reason)
        if persist:
            try:
                estop.ESTOP_FLAG.parent.mkdir(parents=True, exist_ok=True)
                # Nie zapisuj na każdej iteracji, gdy zatrzask już istnieje.
                if not estop.ESTOP_FLAG.exists():
                    estop.ESTOP_FLAG.touch(mode=0o600, exist_ok=True)
                self.persistence_error = None
            except OSError as exc:
                # Zatrzask w pamięci i STOP nie zależą od zapisu na dysku.
                self.persistence_error = f"estop_persistence_failed:{type(exc).__name__}:{exc}"

    def poll(self) -> None:
        if self.blocked():
            self.latch_estop("external_estop")
        elif self.state == "ARMED" and self.arming_mode in {"timed", "journey"} and self.clock() >= self.lease_deadline:
            self.disarm("decision_timeout" if self.arming_mode == "journey" else "consent_expired")
        elif self.state == "ARMED" and os.getenv("MOTION_ENABLE") == "0":
            self.disarm("environment_inhibit")

    def can_actuate(self) -> bool:
        self.poll()
        return self.state == "ARMED" and self.owner in OWNERS

    def _validate_envelope(self, command: dict) -> None:
        if not isinstance(command.get("request_id"), str) or not 0 < len(command["request_id"]) <= 128:
            raise ValueError("request_id_required")
        if not isinstance(command.get("source"), str) or command["source"] not in OWNERS | {'agent'}:
            raise ValueError("unknown_source")
        priority_sequence = self.manual_intervention.priority_sequence(command)
        if priority_sequence is None:
            priority_sequence = self.operator_control.priority_sequence(command)
        if command.get("generation") != self.generation and priority_sequence is None:
            raise ValueError("stale_generation")
        seq = command.get("seq")
        last_seq = self.agent_last_seq if command.get('source') == 'agent' else self.last_seq
        if priority_sequence is not None:
            last_seq = priority_sequence
        if isinstance(seq, bool) or not isinstance(seq, int) or not 0 <= seq < 2**63 or seq <= last_seq:
            raise ValueError("stale_sequence")
        if type(command.get("ts")) not in (int, float):
            raise ValueError("timestamp_required")
        sent = finite_number(command.get("ts"), "timestamp_required")
        if type(command.get("ttl_ms")) is not int:
            raise ValueError("ttl_required")
        ttl = finite_number(command.get("ttl_ms"), "ttl_required")
        age_ms = (self.wall_clock() - sent) * 1000.0
        if not 0 < ttl <= MAX_TTL_MS or age_ms < -100.0 or age_ms > ttl:
            raise ValueError("expired_command")

    def panel_rejection(self, command):
        """Side-effect-free precheck before actuator values can cancel motion."""
        action = command.get("action")
        if not isinstance(action, str) or action not in ACTUATORS or command.get("source") != "manual":
            return None
        panel = command.get("panel_id")
        if "panel_id" in command and (not isinstance(panel, str) or not panel.strip() or len(panel) > 128):
            return "invalid_panel_id"
        if self.manual_intervention.requested(command):
            try:
                validate_intervention(command)
            except ValueError as exc:
                return str(exc)
            return None
        if self.panel_id is not None and panel != self.panel_id:
            return "stale_generation" if command.get("generation") != self.generation else "panel_owner_mismatch"
        return None

    def _authorize_stop(self, command):
        """STOP bypasses ordinary freshness while honoring an explicitly supplied generation."""
        if "expected_generation" in command and (
            not isinstance(command["expected_generation"], str)
            or not command["expected_generation"]
            or command["expected_generation"] != self.generation
        ):
            return False, "stale_stop_generation"
        self.disarm(str(command.get("reason") or "operator_stop"))
        return True, "stopped"

    def _validate_panel_scope(self, command, action):
        """Check panel identity, then metadata, then current ownership in the original order."""
        if action in ACTUATORS | {"arm"} | OPERATOR_ACTIONS:
            panel = command.get("panel_id")
            if "panel_id" in command and (not isinstance(panel, str) or not panel.strip() or len(panel) > 128):
                raise ValueError("invalid_panel_id")
        self._validate_envelope(command)
        if (
            action in ACTUATORS
            and self.panel_id is not None
            and command.get("source") == "manual"
            and command.get("panel_id") != self.panel_id
            and not self.manual_intervention.requested(command)
        ):
            raise ValueError("panel_owner_mismatch")
        if action in ACTUATORS and self.motion_not_before is not None and command["ts"] <= self.motion_not_before:
            raise ValueError("motion_intent_cancelled")

    def _validate_context(self, command):
        """Keep test consent and execution context separate from operator arming."""
        context = command.get("execution_context", "panel")
        if not isinstance(context, str) or context not in {"panel", "test", "agent"}:
            raise ValueError("unknown_execution_context")
        if context == "test" and command.get("test_operator_consent") is not True:
            raise ValueError("test_operator_consent_required")
        return context

    def _authorize_agent(self, command):
        """Consume an agent intent only after signed authority and manual-priority checks."""
        verify_command(command, resolved=True)
        if (
            self.state != 'ARMED'
            or self.arming_mode != 'operator'
            or self.execution_context != 'panel'
            or self.owner != 'manual'
        ):
            raise ValueError('agent_operator_arm_required')
        if command['agent_epoch'] != self.agent_epoch:
            raise ValueError('agent_epoch_stale')
        if self.clock() < self.manual_grace_until:
            raise ValueError('agent_manual_priority')
        if command['intent_id'] in self.agent_intents:
            raise ValueError('agent_intent_already_used')
        self.agent_last_seq = command['seq']
        self.agent_intents.append(command['intent_id'])
        del self.agent_intents[:-32]
        return True, 'authorized'

    @staticmethod
    def _operator_plan(command):
        """Require explicit consent and a specific plan without extending an existing lease."""
        if command.get("operator_consent") is not True:
            raise ValueError("operator_consent_required")
        plan = command.get("operator_plan", command.get("plan"))
        if not isinstance(plan, str) or not 1 <= len(plan.strip()) <= 512:
            raise ValueError("operator_plan_required")
        return plan

    def _clear_estop(self, command):
        """Clear only the latch; a successful reset always leaves the gate disarmed."""
        self._operator_plan(command)
        if estop.external_estop(include_flag=False):
            raise ValueError("external_estop_active")
        try:
            estop.ESTOP_FLAG.unlink(missing_ok=True)
        except OSError as exc:
            self.persistence_error = f"estop_clear_failed:{type(exc).__name__}:{exc}"
            raise ValueError("estop_clear_failed") from exc
        self.persistence_error = None
        self._invalidate("DISARMED", "estop_cleared_disarmed")
        return True, self.reason

    def _arming_parameters(self, command, context):
        """Validate the full consent request before any gate state is changed."""
        if self.state == "ESTOP":
            raise ValueError("estop_latched")
        if os.getenv("MOTION_ENABLE") == "0":
            raise ValueError("environment_inhibit")
        plan = self._operator_plan(command)
        owner = command.get("owner", command.get("source"))
        if not isinstance(owner, str) or owner not in OWNERS:
            raise ValueError("unknown_owner")
        validate_journey_arm(command, owner, context)
        self.operator_control.validate_arm(command, owner, context)
        mode = command.get("arming_mode", "timed")
        if not isinstance(mode, str) or mode not in {"timed", "operator", "journey"}:
            raise ValueError("invalid_arming_mode")
        if mode == "operator" and (context != "panel" or owner != "manual" or "lease_s" in command):
            raise ValueError("operator_arming_panel_only")
        lease = 0.0 if mode in {"operator", "journey"} else finite_number(command.get("lease_s", 15.0), "invalid_lease")
        if mode == "timed" and not 0 < lease <= MAX_LEASE_S:
            raise ValueError("invalid_lease")
        return owner, plan, mode, lease

    @staticmethod
    def _requested_panel(command, owner, mode):
        """Bind only operator/manual or qualified navigation consent to a panel."""
        if owner == "manual" and mode == "operator" or command.get("operator_control_version") == 1:
            return command.get("panel_id")
        return None

    def _authorize_arm(self, command, context):
        """Idempotent arming preserves existing consent and never extends its deadline."""
        owner, plan, mode, lease = self._arming_parameters(command, context)
        requested_panel = self._requested_panel(command, owner, mode)
        if self.state == "ARMED":
            if mode == "journey" and command.get("journey_id") != self.journey.id:
                raise ValueError("navigation_journey_active")
            if (self.owner, self.execution_context, self.arming_mode) != (owner, context, mode):
                raise ValueError("already_armed_disarm_first")
            if self.panel_id != requested_panel:
                raise ValueError("panel_owner_mismatch")
            self.last_seq = command["seq"]
            return True, "already_armed"
        logging.getLogger("motion.permission").info(
            "permission %s -> ARMED reason=operator_consent generation=%s", self.state, self.generation
        )
        self.motion_not_before = None
        self.state = "ARMED"
        self.owner = owner
        self.panel_id = requested_panel
        self.execution_context = context
        self.plan = plan.strip()
        self.reason = "operator_consent"
        self.arming_mode = mode
        self.lease_deadline = self.clock() + lease
        self.last_seq = command["seq"]
        self.invalidate_agent(manual=owner == "manual")
        self.operator_control.arm(command)
        self.journey.arm(command)
        return True, "armed"

    def _authorize_actuator(self, command, action, context):
        """Retain owner, context and navigation-operation checks before consuming a sequence."""
        if action not in ACTUATORS:
            raise ValueError("unknown_action")
        if self.manual_intervention.requested(command):
            self.manual_intervention.transfer(command)
            self.last_seq = command["seq"]
            return True, "operator_intervention"
        if not self.can_actuate():
            raise ValueError("motion_disarmed" if self.state != "ESTOP" else "estop_latched")
        if context != self.execution_context:
            raise ValueError("execution_context_mismatch")
        if command.get("intervene") is True:
            if action not in {"move", "turn"}:
                raise ValueError("operator_intervention_move_only")
            self.operator_control.transfer(command)
        if self.state != "ARMED":
            raise ValueError("navigation_journey_manual_arm_required")
        if command.get("source") != self.owner:
            raise ValueError("owner_mismatch")
        self.operator_control.validate_navigation(command)
        self.journey.validate_goal(command)
        self.last_seq = command["seq"]
        if command.get('source') == 'manual':
            self.manual_intervention.supersede(command)
            self.invalidate_agent(manual=True)
        return True, "authorized"

    def authorize(self, command: dict) -> tuple[bool, str]:
        """Validate in ordered stages; STOP/E-Stop remain independent of freshness."""
        self.poll()
        if not isinstance(command, dict):
            return False, "unknown_action"
        action = command.get("action")
        if not isinstance(action, str):
            return False, "unknown_action"
        if action in {"stop", "disarm"}:
            return self._authorize_stop(command)
        if action == "estop":
            self.latch_estop()
            return True, "estop_latched"
        try:
            self._validate_panel_scope(command, action)
            context = self._validate_context(command)
            if context == "agent" or command.get("source") == "agent":
                return self._authorize_agent(command)
            if action in OPERATOR_ACTIONS:
                self.operator_control.transfer(command)
                return True, self.operator_control.reason
            if action == "clear_estop":
                return self._clear_estop(command)
            if action == "arm":
                return self._authorize_arm(command, context)
            return self._authorize_actuator(command, action, context)
        except ValueError as exc:
            return False, str(exc)

    def snapshot(self) -> dict:
        self.poll()
        return {
            "contract_version": 1,
            "state": self.state,
            "owner": self.owner,
            "panel_control": {"version": 1, "holder": self.panel_id},
            "operator_control": self.operator_control.snapshot(),
            "navigation_journey_version": 1,
            "operator_intervention_version": 1,
            "operator_height_intervention_version": 1,
            "journey": self.journey.snapshot(),
            "execution_context": self.execution_context,
            "panel_motion_enabled": self.state == "ARMED" and self.execution_context == "panel",
            "test_motion_enabled": self.state == "ARMED" and self.execution_context == "test",
            "generation": self.generation,
            "last_seq": self.last_seq,
            "arming_mode": self.arming_mode,
            "lease_remaining_s": None
            if self.arming_mode == "operator"
            else max(0.0, self.lease_deadline - self.clock()),
            "reason": self.reason,
            "plan": self.plan,
            "persistence_error": self.persistence_error,
            "agent_epoch": self.agent_epoch,
            "agent_last_seq": self.agent_last_seq,
            "manual_agent_grace_s": MANUAL_AGENT_GRACE_S,
            "manual_agent_grace_remaining_s": max(0.0, self.manual_grace_until - self.clock()),
        }
