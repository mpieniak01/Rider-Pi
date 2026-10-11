"""Apply immutable software profiles without SDK writes or arming."""

from apps.motion import calibration_profiles as profiles
from apps.motion.dynamics import RampLimits
from apps.odometry.calibration import calibration_status


class CalibrationRuntime:
    def __init__(self, limits):
        self.ceilings = limits
        self.limits = limits
        self.interaction = None
        self.profile_digest = None
        self.source = "legacy_env"
        self.error = None
        self.odometry_error = None
        self.provenance_kind = None
        self.last_ack = None
        self.applied_ack = None
        self.applied_generation = None
        self.pointer = None
        try:
            pointer = profiles.read_active()
            if pointer is not None:
                profile = profiles.read_profile(pointer["profile_digest"])
                self.limits = self.profile_limits(profile)
                self._record(profile, pointer, "saved_profile")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.error = "saved_profile_unavailable:" + str(exc)

    def profile_limits(self, profile):
        if not self.ceilings.valid:
            raise ValueError("initial_motion_limits_invalid")
        values = profile["motion"]
        if any(values[name] > getattr(self.ceilings, name) for name in ("speed_limit", "linear_rate", "turn_rate")):
            raise ValueError("initial_motion_ceiling_exceeded")
        limits = RampLimits(**values, watchdog_s=self.ceilings.watchdog_s, max_dt_s=self.ceilings.max_dt_s)
        if not limits.valid:
            raise ValueError("invalid_motion_limits")
        return limits

    def _record(self, profile, pointer, source):
        self.pointer = pointer
        self.profile_digest = pointer["profile_digest"]
        self.source = source
        self.error = None
        self.odometry_error = calibration_status(profile["odometry"])
        self.provenance_kind = profile["provenance"]["kind"]
        self.interaction = profile.get("interaction")

    def activate(self, command, executor):
        gate = executor.gate
        row = dict(command) if isinstance(command, dict) else {}
        row.setdefault("action", "activate_calibration")
        try:
            gate.poll()
            gate._validate_envelope(row)
            state = gate.snapshot()
            controller = executor.controller
            state.update(
                observed_at=gate.wall_clock(),
                moving=not controller.stopped,
                target={"lx": controller.t_lx, "az": controller.t_az},
                output={"lx": controller.o_lx, "az": controller.o_az},
            )
            validation = profiles.validate_activate(row, state, now=gate.wall_clock())
            if validation:
                raise ValueError(validation)
            if executor.pending is not None or controller.deadline:
                raise ValueError("calibration_requires_idle")
            # Consume once before any disk write; a failed operation is not
            # retried with the same authorization envelope.
            gate.last_seq = row["seq"]
            profile = profiles.read_profile(row["profile_digest"])
            limits = self.profile_limits(profile)
            pointer = profiles.write_active(
                row["profile_digest"],
                request_id=row["request_id"],
                command_generation=row["generation"],
                seq=row["seq"],
                now=gate.wall_clock(),
                activation_state="pending",
            )
            gate.poll()
            if (
                gate.state != "DISARMED"
                or gate.generation != row["generation"]
                or executor.pending is not None
                or controller.deadline
                or not controller.stopped
                or any((controller.t_lx, controller.t_az, controller.o_lx, controller.o_az))
                or not 0 <= (gate.wall_clock() - row["ts"]) * 1000 <= row["ttl_ms"]
            ):
                self.error = "calibration_state_changed_during_apply"
                raise ValueError(self.error)
            # No blocking hardware call occurs between persistence and apply.
            from apps.motion import manual_settings

            shared = manual_settings.read()
            patch = dict(profile["motion"])
            if profile.get("interaction"):
                patch.update(profile["interaction"])
            manual_settings.update(patch, shared["revision"])
            controller.limits = self.limits = limits
            self._record(profile, pointer, "profile")
            # Configuration invalidates every queued authorization envelope,
            # but the controller is already idle: no SDK STOP or ARM here.
            gate.disarm("calibration_applied")
            self.applied_generation = gate.generation
            # Logical acceptance has happened in DISARMED. An E-Stop arriving
            # during commit is a later safety event; it cannot turn this saved
            # software configuration into a rejected request after reboot.
            try:
                self.pointer = profiles.commit_active(
                    row["profile_digest"],
                    request_id=row["request_id"],
                    command_generation=row["generation"],
                    seq=row["seq"],
                )
            except (OSError, ValueError, TypeError, KeyError) as exc:
                self.error = "calibration_commit_failed:" + type(exc).__name__
                raise ValueError(self.error) from exc
            error = None
        except (OSError, ValueError, TypeError, KeyError) as exc:
            error = str(exc) if isinstance(exc, ValueError) else "calibration_apply_failed:" + type(exc).__name__
        self.last_ack = {
            "contract_id": "rider.calibration.ack",
            "contract_version": 1,
            "action": "activate_calibration",
            "status": "rejected" if error else "executed",
            "accepted": error is None,
            "error": error,
            "reason": error or "software_profile_applied",
            "request_id": row.get("request_id"),
            "source": row.get("source"),
            "seq": row.get("seq"),
            "generation": self.applied_generation if error is None else gate.generation,
            "command_generation": row.get("generation"),
            "profile_digest": row.get("profile_digest"),
            "observed_at": gate.wall_clock(),
            "instance_id": executor.instance_id,
            "actuation": False,
            "physical_completion": "unverified",
        }
        if error is None:
            self.applied_ack = dict(self.last_ack)
        executor._publish("calibration.ack", self.last_ack)
        executor.publish_status(force=True)
        return dict(self.last_ack)

    def status(self, *, now, instance_id):
        live = self.source == "profile"
        return {
            "contract_id": "rider.calibration",
            "contract_version": 1,
            "profile_digest": self.profile_digest,
            "source": self.source,
            "error": self.error,
            "odometry_error": self.odometry_error,
            "provenance_kind": self.provenance_kind,
            "interaction": self.interaction,
            "last_ack": self.last_ack,
            "applied_ack": self.applied_ack,
            "observed_at": now,
            "instance_id": instance_id,
            "activation_request_id": self.pointer.get("request_id") if live else None,
            "command_generation": self.pointer.get("command_generation") if live else None,
            "seq": self.pointer.get("seq") if live else None,
            "applied_generation": self.applied_generation,
            "ceilings": {
                key: getattr(self.ceilings, key) if self.ceilings.valid else None
                for key in ("speed_limit", "linear_rate", "turn_rate")
            },
            "actuation": False,
            "physical_completion": "unverified",
        }
