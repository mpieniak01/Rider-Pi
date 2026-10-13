"""Only UART owner and actuator executor. Commands require explicit consent.

Passive tracking topics are deliberately not subscribed. Legacy actuator topic
names may carry the *same* authenticated envelope; bare legacy motion is refused.
"""

from __future__ import annotations

import logging
import signal
import time
import uuid

from apps.motion import manual_settings
from apps.motion.actuator_contract import COMMAND_TOPICS, SUB_TOPICS, validate_actuator  # public re-exports
from apps.motion.calibration_runtime import CalibrationRuntime
from apps.motion.dynamics import RampLimits
from apps.motion.main import MotionController, _make_adapter
from apps.motion.sensor_quality import SensorSamples
from apps.safety.gate import ACTUATORS, MotionGate
from apps.safety.state import write_status
from common.agent_control import is_agent, verify_command
from common.motion_commands import canonical_command  # public re-export

LOG = logging.getLogger("motion.executor")


class MotionExecutor:
    def __init__(self, *, gate=None, adapter=None, publisher=None, status_writer=write_status):
        self.gate = gate or MotionGate()
        self.instance_id = uuid.uuid4().hex
        self.adapter = adapter if adapter is not None else _make_adapter(self.gate)
        self.controller = MotionController(self.adapter, self.gate)
        self.calibration = CalibrationRuntime(self.controller.limits)
        self.controller.limits = self.calibration.limits
        self.publisher = publisher
        self.status_writer = status_writer
        self.last_ack = None
        self.recent_acks = []
        self.pending = None
        self.last_snapshot = 0.0
        self.last_sensors = 0.0
        self.last_firmware = 0.0
        self.firmware = None
        self.sensor_values = {}
        self.sensor_times = {}
        self.sensor_index = 0
        self.samples = SensorSamples(
            self.gate.clock,
            self.gate.wall_clock,
            instance_id=self.instance_id,
            simulated=getattr(self.adapter, "simulated", False),
        )
        self.last_output = 0.0
        self.output_generation = None
        self.output_command_generation = None
        self.output_observed_at = None
        self.error = getattr(self.adapter, "error", None)
        self.controls = None
        self.controls_pending_revision = None
        self.controls_checked_at = 0.0
        self.shutdown = False
        self.intent_source = None
        self.execution_inhibit = None
        self.actuators = {
            "balance": {"enabled": None, "ts": None, "physical_completion": "unverified"},
            "height": {"value": None, "ts": None, "physical_completion": "unverified"},
        }
        # Controller deadline/watchdog stops use the same fault latch.
        self._controller_stop = self.controller.stop
        self.controller.stop = self._stop_hardware
        self.refresh_controls(force=True)
        self.controller.stop()
        self.publish_status(force=True)

    def _hardware_ready(self):
        error = getattr(self.adapter, "error", None)
        if error or not self.adapter.ok():
            self._hardware_fault(error or "hardware_unavailable")
        return bool(not self.shutdown and not self.error and self.adapter.ok())

    def _hardware_fault(self, reason, *, stop=True):
        # A later successful zero write never restores consent or readiness.
        # Recovery requires a newly initialized executor/adapter.
        self.error = self.error or reason
        if self.gate.state == "ARMED":
            self.gate.disarm("hardware_unavailable")
            if stop:
                self.controller.stop()

    def _stop_hardware(self):
        try:
            stopped = self._controller_stop() is True
        except Exception as exc:
            self._hardware_fault(f"hardware_stop_failed:{type(exc).__name__}", stop=False)
            self.output_observed_at = self.gate.wall_clock()
            self.output_command_generation = self.gate.generation
            self.publish_output(force=True, accepted=False)
            self.publish_status(force=True)
            return False
        if not stopped:
            self._hardware_fault(getattr(self.adapter, "error", None) or "hardware_stop_unconfirmed", stop=False)
        elif getattr(self.adapter, "error", None):
            self._hardware_fault(self.adapter.error, stop=False)
        self.output_observed_at = self.gate.wall_clock()
        self.output_command_generation = self.gate.generation
        self.publish_output(force=True, accepted=stopped)
        # A zero write remains valid while idle only with this exact executor
        # heartbeat. Deadline stops also need it before the output ages out.
        self.publish_status(force=True)
        return stopped

    def _publish(self, topic, payload):
        if self.publisher is not None:
            self.publisher.publish(topic, payload, add_ts=False)

    def refresh_controls(self, force=False):
        now = self.gate.clock()
        if not force and self.controls is not None and now - self.controls_checked_at < 0.2:
            return
        self.controls_checked_at = now
        if not self.controller.limits.valid:
            self._hardware_fault("invalid_motion_limits")
            return
        try:
            row = manual_settings.read(blocking=False)
            if self.controls is not None and row["revision"] != self.controls["revision"] and self.controller.deadline:
                # Published idle status can race an admitted goal. Keep that goal's
                # configuration until it ends, and admit no replacement on mixed revisions.
                self.controls_pending_revision = row["revision"]
                return
            self.controls_pending_revision = None
            values = row["values"]
            self.controller.limits = RampLimits(
                speed_limit=values["speed_limit"],
                linear_rate=values["linear_rate"],
                turn_rate=values["turn_rate"],
                linear_deceleration=values["linear_deceleration"],
                turn_deceleration=values["turn_deceleration"],
                reversal_pause=values["reversal_pause"],
                ramp_mode=values["ramp_mode"],
                watchdog_s=self.calibration.ceilings.watchdog_s,
                max_dt_s=self.calibration.ceilings.max_dt_s,
            )
            self.controls = row
        except BlockingIOError:
            return  # Keep dispatch responsive; command admission uses its own nonblocking lock.
        except (ValueError, OSError, TypeError):
            self._hardware_fault("manual_settings_unavailable")
            self.controls = None

    def snapshot(self):
        hardware_ready = self._hardware_ready()
        quality = self.samples.quality()
        ready = hardware_ready and quality["ready"] and self.controller.limits.valid
        state = self.gate.snapshot()
        state.update(
            authorization={
                "authority": "motion-executor",
                "state": state["state"],
                "generation": state["generation"],
                "instance_id": self.instance_id,
                "owner": state["owner"],
                "execution_context": state["execution_context"],
                "arming_mode": state["arming_mode"],
                "confirmed": True,
            },
            execution={
                "ready": ready,
                "inhibit": self.error or quality["error"],
                "motion_not_before": self.gate.motion_not_before,
            },
            manual_settings=self.controls,
            deadline=self.controller.deadline,
            contract_id="rider.safety",
            observed_at=self.gate.wall_clock(),
            ts=self.gate.wall_clock(),
            ready=ready,
            hardware_ready=hardware_ready,
            hardware_initialized=bool(self.adapter.ok()),
            can_move=bool(ready and self.gate.can_actuate()),
            read_only=not bool(ready and self.gate.can_actuate()),
            error=self.error
            or getattr(self.adapter, "error", None)
            or quality["error"]
            or self.controller.limits.status()["error"],
            last_ack=self.last_ack,
            recent_acks=list(self.recent_acks),
            simulated=bool(getattr(self.adapter, "simulated", False)),
            moving=not self.controller.stopped,
            intent_mode=getattr(self.controller, "intent_mode", "pulse"),
            active_source=self.intent_source if self.controller.deadline > self.gate.clock() else None,
            agent_manual_active=bool(self.intent_source == 'manual' and self.controller.deadline > self.gate.clock()),
            target={"lx": self.controller.t_lx, "az": self.controller.t_az},
            output={"lx": self.controller.o_lx, "az": self.controller.o_az},
            uart_owner="motion-executor",
            instance_id=self.instance_id,
            physical_completion="unverified",
            capabilities=self.capabilities(),
            actuators=self.actuators,
            sensor_quality=quality,
            dynamics=self.controller.limits.status(),
            sdk_output=self.sdk_output(),
            calibration=dict(
                self.calibration.status(now=self.gate.wall_clock(), instance_id=self.instance_id),
                motion_settings=self.controls,
                motion_authority="device_settings",
            ),
        )
        return state

    def capabilities(self):
        ready = self._hardware_ready() and self.controller.limits.valid
        method = getattr(self.adapter, "capabilities", None)
        if callable(method):
            result = method()
            if not ready:
                return {name: {**value, "available": False} for name, value in result.items()}
            return result
        return {
            action: {
                "available": ready and action in {"move", "turn", "balance", "height"},
                "stop_verified": True,
                "verification": "simulated",
            }
            for action in {"move", "turn", "balance", "height", "action"}
        }

    def sdk_output(self, accepted=True):
        method = getattr(self.adapter, "output_status", None)
        output = method() if callable(method) else {"linear_step": None, "turn_step": None}
        return {
            **output,
            "contract_id": "rider.motion.output",
            "contract_version": 1,
            "observed_at": self.output_observed_at,
            "generation": self.output_command_generation,
            "accepted": bool(accepted and not self.error and self.adapter.ok()),
            "stopped": self.controller.stopped,
            "source": "motion-executor",
            "instance_id": self.instance_id,
            "physical_completion": "unverified",
        }

    def publish_output(self, *, force=False, accepted=True):
        now = self.gate.clock()
        if force or self.output_generation != self.gate.generation or now - self.last_output >= 0.1:
            self._publish("motion.output", self.sdk_output(accepted))
            self.last_output = now
            self.output_generation = self.gate.generation

    def publish_status(self, *, force=False):
        now = self.gate.clock()
        if force or now - self.last_snapshot >= 1.0:
            snapshot = self.snapshot()
            self.status_writer(snapshot)
            self._publish("motion.state", snapshot)
            self.last_snapshot = now

    def _ack(self, command, status, reason, **details):
        self.last_ack = {
            "contract_id": "rider.motion.ack",
            "contract_version": 1,
            "request_id": command.get("request_id", command.get("rid")),
            "action": command.get("action"),
            "status": status,
            "reason": reason,
            "source": command.get("source"),
            "execution_context": command.get("execution_context"),
            "channel": command.get("channel"),
            "intent_id": command.get("intent_id"),
            "agent_epoch": command.get("agent_epoch"),
            "seq": command.get("seq"),
            "generation": self.gate.generation,
            "command_generation": command.get("generation"),
            "observed_at": self.gate.wall_clock(),
            "physical_completion": "unverified",
            "requested": {key: command.get(key) for key in ("direction", "vx", "yaw", "duration", "settings_revision")},
            "output": {"lx": self.controller.o_lx, "az": self.controller.o_az},
            "accepted": status in {"accepted", "executed"},
            "error": reason if status == "rejected" else None,
            **details,
        }
        if status in {"executed", "rejected"}:
            self.recent_acks.append(dict(self.last_ack))
            del self.recent_acks[:-16]
        self._publish("motion.ack", self.last_ack)
        self.publish_status(force=True)
        return dict(self.last_ack)

    def apply(self, payload, *, topic="motion.command"):
        # STOP must never wait for filesystem locks, profile reads or revisions.
        try:
            action = canonical_command(topic, payload).get("action")
        except (ValueError, TypeError, OverflowError):
            action = None
        if action in {"stop", "disarm", "estop"}:
            return self._apply(payload, topic=topic)
        try:
            with manual_settings.locked(blocking=False):
                return self._apply(payload, topic=topic)
        except (OSError, ValueError, TypeError) as exc:
            return self._ack(payload if isinstance(payload, dict) else {}, "rejected", str(exc))

    def _apply(self, payload, *, topic="motion.command"):
        if topic == "calibration.activate":
            return self.calibration.activate(payload, self)
        if not isinstance(payload, dict) or topic not in COMMAND_TOPICS:
            return self._ack({}, "rejected", "passive_or_invalid_command")
        try:
            command = canonical_command(topic, payload)
        except (TypeError, ValueError, OverflowError):
            # Invalid alias frames use the ordinary validation/cancellation
            # path rather than escaping the executor loop.
            command = {**payload, "action": "move", "duration": None}
        action = command.get("action")
        agent = is_agent(command)
        if agent and action not in {'stop', 'disarm', 'estop'}:
            try:
                verify_command(command)
                if self.intent_source == 'manual' and self.controller.deadline > self.gate.clock():
                    raise ValueError('agent_manual_priority')
            except ValueError as exc:
                return self._ack(command, 'rejected', str(exc))
        mode = command.get("mode", "pulse")
        if action in {"move", "turn"}:
            if not isinstance(mode, str) or mode not in {"pulse", "hold", "release"}:
                return self._ack(command, "rejected", "unsupported_motion_mode")
            if mode != "pulse" and not (
                command.get("device_settings") is True
                and command.get("source") == "manual"
                and command.get("execution_context") == "panel"
                and self.gate.arming_mode == "operator"
                and self.gate.execution_context == "panel"
                and self.gate.owner == "manual"
            ):
                return self._ack(command, "rejected", "hold_operator_panel_only")
        if action in {"arm", "move", "turn", "height", "balance", "stabilization", "action"}:
            if not self.controller.limits.valid:
                self._hardware_fault("invalid_motion_limits")
            self.refresh_controls(force=True)
        if action in {"move", "turn", "height", "balance", "stabilization", "action"}:
            if self.controls_pending_revision is not None:
                return self._ack(command, "rejected", "manual_settings_requires_idle")
            if (
                self.controls is None
                or type(command.get("settings_revision")) is not int
                or command["settings_revision"] != self.controls["revision"]
            ):
                return self._ack(command, "rejected", "manual_settings_stale")
            if action in {"move", "turn"} and "direction" in command:
                try:
                    expected = manual_settings.pulse(self.controls, command["direction"])
                    if command.get("device_settings") is True:
                        command.update(expected)
                        if mode in {"hold", "release"}:
                            command["duration"] = manual_settings.HOLD_TIMEOUT_S
                        if mode == "release":
                            command.update(vx=0.0, yaw=0.0)
                    elif any(command.get(key) != value for key, value in expected.items()):
                        return self._ack(command, "rejected", "manual_settings_mismatch")
                except ValueError as exc:
                    return self._ack(command, "rejected", str(exc))

        is_actuator = isinstance(action, str) and action in ACTUATORS
        if (
            isinstance(action, str)
            and action not in {"stop", "disarm", "estop"}
            and self.controller.deadline
            and self.gate.clock() >= self.controller.deadline
        ):
            self.controller.expire_goal()
            if self.pending is not None:
                previous, self.pending = self.pending, None
                self._ack(previous, "rejected", "motion_goal_timeout")
        try:
            values = validate_actuator(command)
            if action in {"move", "turn"}:
                manual_settings.validate_command(self.controls, values, mode=mode)
        except ValueError as exc:
            if is_actuator and self.controller.deadline and not agent:
                self.gate.cancel_motion("invalid_motion_intent")
                self.controller.stop()
                previous, self.pending = self.pending, None
                if previous is not None:
                    self._ack(previous, "rejected", "invalid_motion_intent", cancelled_by=command.get("request_id"))
            return self._ack(command, "rejected", str(exc))
        authorized, reason = self.gate.authorize(command)
        if not authorized:
            # Delayed renewals never undo a newer manual intent or release.
            obsolete = reason in {
                "stale_sequence",
                "stale_generation",
                "expired_command",
                "motion_intent_cancelled",
            }
            if is_actuator and self.controller.deadline and not obsolete and not agent:
                self.gate.cancel_motion("invalid_motion_intent")
                self.controller.stop()
                previous, self.pending = self.pending, None
                if previous is not None:
                    self._ack(previous, "rejected", "invalid_motion_intent", cancelled_by=command.get("request_id"))
            return self._ack(command, "rejected", reason)
        if action in {"stop", "disarm", "estop", "clear_estop"}:
            self.intent_source = None
            pending, self.pending = self.pending, None
            stopped = self.controller.stop()
            if pending is not None:
                self._ack(pending, "rejected", f"cancelled_by_{action}", cancelled_by=command.get("request_id"))
            # Ostatni ACK pozostaje ACK zatrzymania, wcześniejszy cel ma osobny
            # terminalny wpis w ledgerze zamiast wiecznego pending.
            return self._ack(
                command,
                "executed" if stopped else "rejected",
                reason if stopped else "hardware_stop_unconfirmed",
                gate_reason=reason,
                hardware_stop_sent=stopped,
            )
        if action == "arm":
            if not self._hardware_ready():
                self.gate.disarm("hardware_unavailable")
                return self._ack(command, "rejected", "hardware_unavailable")
            if not self.controller.limits.valid:
                self.gate.disarm("invalid_motion_limits")
                self.controller.stop()
                return self._ack(command, "rejected", "invalid_motion_limits")
            return self._ack(command, "executed", "armed_no_actuation")
        if action in ACTUATORS:
            if not self._hardware_ready():
                self.controller.stop()
                return self._ack(command, "rejected", "hardware_unavailable")
            quality = self.samples.quality()
            if not quality["ready"] or not self.controller.limits.valid:
                reason = quality["error"] or "invalid_motion_limits"
                self._inhibit_motion(reason)
                return self._ack(command, "rejected", reason)
            capability = self.capabilities().get("balance" if action == "stabilization" else action, {})
            if not capability.get("available") or (
                action not in {"height", "balance", "stabilization"} and not capability.get("stop_verified")
            ):
                return self._ack(command, "rejected", "manual_characterization_required")
            if command.get('source') == 'manual' and self.intent_source == 'agent' and action not in {'move', 'turn'}:
                previous, self.pending = self.pending, None
                self.controller.stop()
                self.intent_source = None
                if previous is not None:
                    self._ack(previous, 'rejected', 'manual_takeover', cancelled_by=command.get('request_id'))
        if action in {"move", "turn"}:
            if not self.controller.drive(
                values["vx"],
                values["yaw"],
                values["duration"],
                panel_pulse=command.get("device_settings") is True,
                mode=mode,
            ):
                return self._ack(command, "rejected", "motion_disarmed")
            previous, self.pending = self.pending, None
            self.intent_source = command.get('source')
            if previous is not None:
                self._ack(previous, "rejected", "goal_superseded", superseded_by=command.get("request_id"))
            if values["vx"] == 0 and values["yaw"] == 0 and mode != "release":
                self.output_observed_at = self.gate.wall_clock()
                self.publish_output(force=True)
                return self._ack(command, "executed", "sdk_zero_accepted")
            self.pending = command
            return self._ack(command, "accepted", "goal_accepted")
        method, argument = {
            "balance": ("enable_balance", values.get("enabled")),
            "stabilization": ("enable_balance", values.get("enabled")),
            "height": ("set_height", values.get("height")),
            "action": ("action", values.get("name")),
        }[action]
        if getattr(self.adapter, method)(argument):
            if action in {"balance", "height"}:
                key = "enabled" if action == "balance" else "value"
                self.actuators[action] = {
                    key: command.get(key if action == "balance" else "height"),
                    "ts": self.gate.wall_clock(),
                    "physical_completion": "unverified",
                }
            return self._ack(command, "executed", "sdk_accepted")
        self._hardware_fault(getattr(self.adapter, "error", None) or "actuator_failed")
        self.gate.disarm("actuator_failed")
        self.controller.stop()
        return self._ack(command, "rejected", "actuator_failed")

    def _inhibit_motion(self, reason):
        if self.execution_inhibit != reason:
            self.execution_inhibit = reason
            self.gate.cancel_motion(reason)
            previous, self.pending = self.pending, None
            self.controller.stop()
            if previous is not None:
                self._ack(previous, "rejected", reason)

    def tick(self, dt):
        if not self.controller.deadline:
            self.refresh_controls()
        generation = self.gate.generation
        self._hardware_ready()
        self.gate.poll()
        quality = self.samples.quality()
        if self.gate.state == "ARMED" and not quality["ready"]:
            self._inhibit_motion(quality["error"])
        elif quality["ready"]:
            self.execution_inhibit = None
        if generation != self.gate.generation:
            pending, self.pending = self.pending, None
            self.controller.stop()
            if pending is not None:
                self._ack(pending, "rejected", self.gate.reason)
            self.publish_status(force=True)
        try:
            executed = self.controller.tick(dt)
        except Exception as exc:
            self._hardware_fault(f"actuator_transport_failed:{type(exc).__name__}")
            self.controller.stop()
            executed = False
        if self.gate.reason == "actuator_failed":
            self._hardware_fault(getattr(self.adapter, "error", None) or "actuator_failed")
        if executed:
            self.output_observed_at = self.gate.wall_clock()
            self.output_command_generation = self.gate.generation
            self.publish_output()
        if self.pending is not None and executed:
            pending, self.pending = self.pending, None
            self._ack(pending, "executed", "sdk_accepted")
        elif self.pending is not None and not self.controller.deadline:
            pending, self.pending = self.pending, None
            reason = self.gate.reason if self.gate.state != "ARMED" else "goal_expired_before_execution"
            self._ack(pending, "rejected", reason)
        self.publish_status()

    def process_batch(self, messages):
        commands = [
            (topic, payload) for topic, payload in messages if topic in COMMAND_TOPICS and isinstance(payload, dict)
        ]
        stops = [
            (topic, payload)
            for topic, payload in commands
            if isinstance(canonical_command(topic, payload).get("action"), str)
            and canonical_command(topic, payload).get("action") in {"stop", "disarm", "estop"}
        ]
        if stops:
            # No goal in the same received burst is ever applied around STOP.
            # Preserve its ACK snapshot; cancellation events cannot hide it.
            for topic, payload in stops:
                self.apply(payload, topic=topic)
            return
        for topic, payload in commands:
            self.apply(payload, topic=topic)

    def poll_sensors(self):
        from apps.motion.telemetry_poll import poll

        poll(self)

    def close(self, reason="executor_shutdown"):
        self.shutdown = True
        self.pending = None
        self.gate.disarm(reason)
        try:
            self.controller.stop()
        finally:
            self.adapter.close()
            self.publish_status(force=True)


def main() -> int:
    from common import bus

    executor = None
    sub = pub = None
    stopping = False

    def stop_signal(_signum, _frame):
        nonlocal stopping
        stopping = True
        if executor is not None:
            executor.gate.disarm("process_signal")
            executor.controller.stop()

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, stop_signal)
    try:
        sub, pub = bus.BusSub(SUB_TOPICS), bus.BusPub()
        executor = MotionExecutor(publisher=pub)
        previous = time.monotonic()
        while not stopping:
            topic, payload = sub.recv(timeout_ms=20)
            messages = []
            if topic in COMMAND_TOPICS:
                messages.append((topic, payload))
            # Drain a bounded burst before executing a goal. Any STOP wins this
            # burst and invalidates earlier or later queued generation tokens.
            for _ in range(63):
                topic, payload = sub.recv(timeout_ms=0)
                if topic is None:
                    break
                if topic in COMMAND_TOPICS:
                    messages.append((topic, payload))
            executor.process_batch(messages)
            now = time.monotonic()
            executor.tick(now - previous)
            previous = now
            executor.poll_sensors()
        return 0
    finally:
        if executor is not None:
            executor.close()
        if sub is not None:
            sub.close()
        if pub is not None:
            pub.close()


if __name__ == "__main__":
    raise SystemExit(main())
