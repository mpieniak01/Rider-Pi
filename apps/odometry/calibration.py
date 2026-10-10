"""Load recorded SDK step measurements; never infer physical units from UI speed."""

import json
import os
from pathlib import Path

from common.data_quality import finite_number, sample_status


def load_calibration(path=None):
    path = path or os.getenv("ODOMETRY_CALIBRATION_PATH")
    if not path:
        return {}
    try:
        record = Path(path)
        if record.stat().st_size > 65536:
            return {}
        value = json.loads(record.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def calibration_status(record):
    if (
        not isinstance(record, dict)
        or type(record.get("schema_version")) is not int
        or record["schema_version"] != 1
        or record.get("manual_verified") is not True
    ):
        return "manual_calibration_required"
    if not isinstance(record.get("measurement_id"), str) or not record["measurement_id"].strip():
        return "measurement_id_required"
    conditions = record.get("conditions")
    if not isinstance(conditions, dict) or any(
        not conditions.get(key) for key in ("firmware", "surface", "load", "battery")
    ):
        return "measurement_conditions_required"
    if record.get("imu_yaw_sign") not in (-1, 1) or type(record.get("imu_yaw_sign")) is bool:
        return "imu_yaw_direction_unverified"
    for name in ("linear_m_s", "turn_rad_s"):
        table = record.get(name)
        if not isinstance(table, dict) or not table:
            return "sdk_step_measurements_required"
        for key, value in table.items():
            try:
                step = int(key)
            except (ValueError, TypeError):
                return "invalid_sdk_step_measurement"
            if str(step) != key or step == 0 or not finite_number(value) or value * step <= 0:
                return "invalid_sdk_step_measurement"
    return None


def measured_rate(record, table, step):
    if step == 0:
        return 0.0
    value = record.get(table, {}).get(str(step))
    return value if finite_number(value) else None


class CalibrationBinding:
    """Follow only the live executor's exact immutable software revision."""

    def __init__(self, estimator):
        self.estimator = estimator
        self.profile_digest = None
        self.source = "legacy_file"
        self.error = None
        self.motion_instance_id = self.generation = None
        self.activation_request_id = self.seq = None
        self.applied_generation = None
        self.observed_at = None
        self._confirmation = None
        self._last_state_observed_at = None
        try:
            from apps.motion.calibration_profiles import read_active, read_profile

            pointer = read_active()
            if pointer is not None:
                digest = pointer["profile_digest"]
                profile = read_profile(digest)
                estimator.calibration = profile["odometry"]
                estimator.calibration_error = calibration_status(estimator.calibration)
                estimator.calibration_digest = self.profile_digest = digest
                self.source = "saved_profile"
                self.error = "motion_profile_confirmation_required"
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.source = "saved_profile"
            self.error = "saved_profile_unavailable:" + str(exc)
            estimator.calibration = {}
            estimator.calibration_error = "manual_calibration_required"

    def _invalidate(self, error, digest=None):
        if self.error != error or self.profile_digest != digest or self._confirmation is not None:
            self.estimator.reset_calibration({}, digest)
        self.error = error
        self.profile_digest = digest
        self._confirmation = None
        self.motion_instance_id = self.generation = None
        self.activation_request_id = self.seq = None
        self.applied_generation = None
        self.observed_at = None

    def observe(self, payload):
        from apps.motion.calibration_profiles import read_profile

        row = payload if isinstance(payload, dict) else {}
        config = row.get("calibration")
        if (
            self.source == "legacy_file"
            and self.profile_digest is None
            and (
                config is None
                or isinstance(config, dict)
                and config.get("source") == "legacy_env"
                and not config.get("error")
            )
        ):
            return
        digest = config.get("profile_digest") if isinstance(config, dict) else None
        # A different/failed configuration immediately destroys the old frame,
        # even while ARMED. Loading itself waits for a DISARMED observation.
        valid = sample_status(
            {key: row.get(key) for key in ("observed_at", "offline", "stale")},
            max_age_s=3.0,
            now=self.estimator.wall_clock(),
            previous_ts=self._last_state_observed_at,
        )["ready"]
        valid = valid and isinstance(config, dict) and not config.get("error")
        valid = valid and sample_status(config, max_age_s=3.0, now=self.estimator.wall_clock())["ready"]
        valid = valid and config["observed_at"] <= row["observed_at"]
        valid = valid and type(row.get("contract_version")) is int and row["contract_version"] == 1
        valid = valid and row.get("uart_owner") == "motion-executor"
        valid = valid and isinstance(row.get("instance_id"), str) and bool(row["instance_id"])
        valid = valid and isinstance(row.get("generation"), str) and bool(row["generation"])
        valid = valid and config.get("instance_id") == row.get("instance_id")
        valid = valid and isinstance(digest, str) and len(digest) == 64
        valid = valid and config.get("source") in {"profile", "saved_profile"}
        if not valid:
            self._invalidate("motion_profile_unconfirmed", digest)
            return
        self._last_state_observed_at = row["observed_at"]
        transaction = (
            digest,
            row["instance_id"],
            config.get("activation_request_id"),
            config.get("command_generation"),
            config.get("seq"),
            config.get("applied_generation"),
        )
        if self._confirmation == transaction:
            # Later ARM/STOP is not a new calibration operation. Never restore
            # a reference here, and never reinterpret an old revision.
            self.observed_at = config["observed_at"]
            return
        if (
            row.get("state") != "DISARMED"
            or row.get("moving") is not False
            or any(
                not isinstance(row.get(name), dict)
                or any(not finite_number(row[name].get(key)) or row[name][key] != 0 for key in ("lx", "az"))
                for name in ("target", "output")
            )
        ):
            self._invalidate("calibration_requires_idle_disarmed", digest)
            return
        live = config["source"] == "profile"
        ack = config.get("applied_ack")
        if live and (
            not isinstance(ack, dict)
            or ack.get("status") != "executed"
            or ack.get("accepted") is not True
            or ack.get("actuation") is not False
            or ack.get("action") != "activate_calibration"
            or ack.get("profile_digest") != digest
            or ack.get("instance_id") != row["instance_id"]
            or not isinstance(config.get("command_generation"), str)
            or not config["command_generation"]
            or ack.get("command_generation") != config["command_generation"]
            or not isinstance(config.get("applied_generation"), str)
            or not config["applied_generation"]
            or ack.get("generation") != config["applied_generation"]
            or ack.get("source") != "manual"
            or ack.get("error")
            or not isinstance(config.get("activation_request_id"), str)
            or not config["activation_request_id"]
            or ack.get("request_id") != config["activation_request_id"]
            or type(config.get("seq")) is not int
            or ack.get("seq") != config["seq"]
            or not finite_number(ack.get("observed_at"))
            or not ack["observed_at"] <= config["observed_at"] <= row["observed_at"]
        ):
            self._invalidate("calibration_activation_unconfirmed", digest)
            return
        try:
            profile = read_profile(digest)
        except (OSError, ValueError, TypeError, KeyError):
            self._invalidate("calibration_revision_unavailable", digest)
            return
        self.estimator.reset_calibration(profile["odometry"], digest)
        # Reset is an estimator boundary, not a new SDK STOP witness. A direct
        # zero received after this observation is required for a new reference.
        self.estimator.calibration_applied_at = config["observed_at"]
        self.profile_digest, self.source, self.error = digest, config["source"], None
        self.motion_instance_id, self.generation = row["instance_id"], config.get("command_generation")
        self.activation_request_id = config.get("activation_request_id") if live else None
        self.seq = config.get("seq") if live else None
        self.applied_generation = config.get("applied_generation") if live else None
        self.observed_at = config["observed_at"]
        self._confirmation = transaction

    def status(self):
        return {
            "profile_digest": self.profile_digest,
            "source": self.source,
            "error": self.error,
            "odometry_error": self.estimator.calibration_error,
            "model_ready": self.estimator.quality()["data_ready"],
            "record_verified": self.estimator.calibration.get("manual_verified") is True,
            "activation_request_id": self.activation_request_id,
            "command_generation": self.generation if self.source == "profile" else None,
            "seq": self.seq,
            "applied_generation": self.applied_generation,
            "motion_instance_id": self.motion_instance_id,
            "observed_at": self.observed_at,
            "actuation": False,
            "physical_completion": "unverified",
        }
