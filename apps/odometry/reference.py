"""Explicit operator reference bound to one live estimator; never actuates."""

import fcntl
import json
import os
import time
import uuid
from pathlib import Path

from apps.safety.state import atomic_write, read_status
from common.data_quality import finite_number


def reference_paths():
    root = Path(os.getenv("ODOMETRY_STATE_DIR", "/run/rider-motion"))
    return root / "odometry-state.json", root / "odometry-reference-seq.json"


class ReferenceControl:
    def __init__(self, estimator, publisher, *, safety_reader=read_status, clock=time.time):
        self.estimator, self.publisher = estimator, publisher
        self.safety_reader, self.clock = safety_reader, clock
        self.started_at = clock()
        self.instance_id = uuid.uuid4().hex
        self.last_ack = None
        self.last_status = 0.0

    def _ack(self, command, *, error=None):
        self.last_ack = {
            "request_id": command.get("request_id"),
            "action": "reference",
            "source": command.get("source"),
            "seq": command.get("seq"),
            "command_generation": command.get("generation"),
            "generation": self.safety_reader().get("generation"),
            "status": "rejected" if error else "executed",
            "accepted": error is None,
            "error": error,
            "observed_at": self.clock(),
            "reference_id": self.estimator.reference_id,
            "profile_digest": self.estimator.calibration_digest,
            "home": self.estimator.home,
            "instance_id": self.instance_id,
            "physical_completion": "unverified",
            "reference_confirmation": "operator_reported" if error is None else "unconfirmed",
            "actuation": False,
        }
        self.publisher.publish("odometry.reference.ack", self.last_ack, add_ts=False)
        self.publish_status(force=True)
        return self.last_ack

    def apply(self, payload):
        row = payload if isinstance(payload, dict) else {}
        state = self.safety_reader()
        error = validate_reference(row, state, now=self.clock(), started_at=self.started_at)
        if error:
            return self._ack(row, error=error)
        digest = row.get("profile_digest")
        if digest is not None or self.estimator.calibration_digest is not None:
            binding = self.estimator.calibration_state()
            config = state.get("calibration", {})
            observed = binding.get("observed_at")
            if (
                self.estimator.calibration_digest != digest
                or binding.get("error")
                or binding.get("profile_digest") != digest
                or binding.get("motion_instance_id") != state.get("instance_id")
                or any(
                    type(binding.get(key)) is not type(config.get(key)) or binding.get(key) != config.get(key)
                    for key in ("source", "activation_request_id", "command_generation", "seq", "applied_generation")
                )
                or not finite_number(observed)
                or not 0 <= self.clock() - observed <= 3.0
            ):
                return self._ack(row, error="reference_profile_unconfirmed")
        _, sequence_path = reference_paths()
        try:
            sequence_path.parent.mkdir(parents=True, exist_ok=True)
            with sequence_path.with_suffix(".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                previous = {}
                if sequence_path.exists():
                    if sequence_path.stat().st_size > 65536:
                        raise ValueError("reference_journal_invalid")
                    previous = json.loads(sequence_path.read_text(encoding="utf-8"))
                    if not isinstance(previous, dict):
                        raise ValueError("reference_journal_invalid")
                last_seq = previous.get("seq") if previous.get("generation") == row["generation"] else -1
                if type(last_seq) is not int or row["seq"] <= last_seq:
                    return self._ack(row, error="reference_replayed")
                atomic_write(
                    sequence_path,
                    {
                        "generation": row["generation"],
                        "seq": row["seq"],
                        "request_id": row["request_id"],
                        "instance_id": self.instance_id,
                    },
                )
        except (OSError, ValueError, TypeError):
            return self._ack(row, error="reference_journal_unavailable")
        if not self.estimator.set_reference(
            reference_id=row["request_id"],
            operator_consent=True,
            x=row["x"],
            y=row["y"],
            theta=row["theta"],
            home_operator_confirmed=row.get("home_operator_confirmed", False),
            home_x=row.get("home_x"),
            home_y=row.get("home_y"),
        ):
            return self._ack(row, error="reference_denied")
        # Recheck safety immediately before reporting this reference as current.
        latest = self.safety_reader()
        if validate_reference(row, latest, now=self.clock(), started_at=self.started_at):
            self.estimator.reference_verified = False
            self.estimator.reference_id = None
            self.estimator.home = None
            return self._ack(row, error="safety_changed_during_reference")
        return self._ack(row)

    def publish_status(self, *, force=False):
        now = self.clock()
        if not force and now - self.last_status < 1.0:
            return
        self.last_status = now
        status_path, _ = reference_paths()
        snapshot = {
            "contract_version": 1,
            "observed_at": now,
            "instance_id": self.instance_id,
            "started_at": self.started_at,
            "reference_verified": self.estimator.reference_verified,
            "reference_id": self.estimator.reference_id,
            "home": self.estimator.home,
            "last_ack": self.last_ack,
            "pose": self.estimator.get_pose(),
            "calibration": self.estimator.calibration_state(),
            "actuation": False,
        }
        try:
            atomic_write(status_path, snapshot)
        except OSError:
            # An unavailable status channel never becomes an operator ACK.
            pass


def validate_reference(row, state, *, now, started_at=None):
    if not isinstance(row, dict) or not isinstance(state, dict):
        return "invalid_reference"
    if (
        type(state.get("contract_version")) is not int
        or state["contract_version"] != 1
        or state.get("ready") is not True
        or state.get("state") != "DISARMED"
        or state.get("moving") is not False
    ):
        return "reference_requires_fresh_disarmed"
    observed = state.get("observed_at")
    if not finite_number(observed) or not 0 <= now - observed <= 3.0:
        return "safety_stale"
    if row.get("generation") != state.get("generation") or not isinstance(row.get("generation"), str):
        return "stale_generation"
    config = state.get("calibration")
    current_digest = config.get("profile_digest") if isinstance(config, dict) else None
    requested_digest = row.get("profile_digest")
    if current_digest is not None or requested_digest is not None:
        if (
            not isinstance(requested_digest, str)
            or len(requested_digest) != 64
            or any(char not in "0123456789abcdef" for char in requested_digest)
            or requested_digest != current_digest
            or config.get("error")
            or config.get("instance_id") != state.get("instance_id")
            or not finite_number(config.get("observed_at"))
            or not 0 <= now - config["observed_at"] <= 3.0
        ):
            return "reference_profile_mismatch"
    if row.get("source") != "manual" or type(row.get("seq")) is not int or row["seq"] < 0:
        return "reference_metadata_required"
    if not isinstance(row.get("request_id"), str) or not 0 < len(row["request_id"]) <= 128:
        return "request_id_required"
    ts, ttl = row.get("ts"), row.get("ttl_ms")
    if not finite_number(ts) or not finite_number(ttl) or not 0 < ttl <= 500 or not 0 <= now - ts <= ttl / 1000:
        return "reference_expired"
    if started_at is not None and ts < started_at:
        return "reference_before_process_start"
    if (
        row.get("operator_consent") is not True
        or not isinstance(row.get("operator_plan"), str)
        or not row["operator_plan"].strip()
    ):
        return "reference_operator_plan_required"
    if not all(finite_number(row.get(key)) for key in ("x", "y", "theta")):
        return "reference_coordinates_required"
    confirmed = row.get("home_operator_confirmed", False)
    if (
        type(confirmed) is not bool
        or (confirmed and not all(finite_number(row.get(key)) for key in ("home_x", "home_y")))
        or (not confirmed and (row.get("home_x") is not None or row.get("home_y") is not None))
    ):
        return "explicit_home_coordinates_required"
    return None
