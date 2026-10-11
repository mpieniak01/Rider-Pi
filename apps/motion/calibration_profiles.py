"""Bounded local calibration revisions; saving never activates or actuates."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from apps.odometry.calibration import calibration_status
from common.data_quality import finite_number

MAX_BYTES = 65536
MAX_REVISIONS = 64
MAX_MEASUREMENTS = 128
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def storage_dir():
    default = Path(__file__).resolve().parents[2] / "config" / "local" / "motion-calibration"
    override = os.getenv("RIDER_CALIBRATION_DIR")
    value = Path(override) if override else default
    if not value.is_absolute():
        raise ValueError("calibration_directory_must_be_absolute")
    return value


def _text(value, name, *, limit=4096, required=False):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value or required and not value.strip():
        raise ValueError(name)
    return value


def _bounded(value, depth=0):
    if depth > 8:
        raise ValueError("profile_too_deep")
    if value is None or type(value) is bool:
        return value
    if isinstance(value, str):
        return _text(value, "profile_string_invalid")
    if type(value) in (int, float):
        if not finite_number(value):
            raise ValueError("profile_number_invalid")
        return value
    if isinstance(value, list) and len(value) <= MAX_MEASUREMENTS:
        return [_bounded(item, depth + 1) for item in value]
    if isinstance(value, dict) and len(value) <= MAX_MEASUREMENTS:
        return {
            _text(key, "profile_key_invalid", limit=128, required=True): _bounded(item, depth + 1)
            for key, item in value.items()
        }
    raise ValueError("profile_value_invalid")


def _encode(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("profile_oversized")
    return raw


def _fields(value, expected, code):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(code)


def validate_profile(profile):
    """Return canonical content. Historical/draft records cannot assert verification."""
    value = _bounded(profile)
    required = {"schema_version", "name", "provenance", "motion", "odometry", "measurements"}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {"interaction"}:
        raise ValueError("profile_schema")
    if "interaction" in value:
        interaction = value["interaction"]
        _fields(interaction, ("linear_speed", "turn_speed", "pulse_duration"), "profile_interaction_fields")
        for field in ("linear_speed", "turn_speed", "pulse_duration"):
            number = interaction[field]
            upper = 0.25 if field == "pulse_duration" else 1.0
            lower = 0.01 if field == "pulse_duration" else 0.0
            if not finite_number(number) or not lower <= number <= upper:
                raise ValueError("profile_interaction_" + field)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("profile_schema_version")
    value["name"] = _text(value["name"], "profile_name", limit=80, required=True).strip()
    provenance = value["provenance"]
    _fields(provenance, ("kind", "notes"), "profile_provenance")
    if provenance["kind"] not in ("draft", "historical", "manual"):
        raise ValueError("profile_provenance_kind")
    _text(provenance["notes"], "profile_provenance_notes")
    motion = value["motion"]
    _fields(motion, ("speed_limit", "linear_rate", "turn_rate"), "profile_motion_fields")
    for field, ceiling in (("speed_limit", 1), ("linear_rate", 100), ("turn_rate", 100)):
        if not finite_number(motion[field]) or not 0 < motion[field] <= ceiling:
            raise ValueError("profile_motion_" + field)
        motion[field] = float(motion[field])
    record = value["odometry"]
    _fields(
        record,
        (
            "schema_version",
            "manual_verified",
            "measurement_id",
            "conditions",
            "imu_yaw_sign",
            "linear_m_s",
            "turn_rad_s",
            "observations",
        ),
        "profile_odometry_fields",
    )
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise ValueError("profile_odometry_schema")
    if type(record["manual_verified"]) is not bool:
        raise ValueError("profile_odometry_verification")
    if provenance["kind"] != "manual":
        record["manual_verified"] = False
    _text(record["measurement_id"], "profile_measurement_id", limit=128)
    conditions = record["conditions"]
    if not isinstance(conditions, dict) or not {"firmware", "surface", "load", "battery"} <= set(conditions):
        raise ValueError("profile_conditions")
    for item in conditions.values():
        _text(item, "profile_condition", limit=1024)
    if record["imu_yaw_sign"] is not None and (
        type(record["imu_yaw_sign"]) is not int or record["imu_yaw_sign"] not in (-1, 1)
    ):
        raise ValueError("profile_imu_yaw_sign")
    for field, ceiling in (("linear_m_s", 127), ("turn_rad_s", 180)):
        table = record[field]
        if not isinstance(table, dict) or len(table) > 2 * ceiling:
            raise ValueError("profile_sdk_table")
        for key, item in table.items():
            try:
                step = int(key)
            except (TypeError, ValueError):
                raise ValueError("profile_sdk_step") from None
            minimum = 1
            if str(step) != key or not minimum <= abs(step) <= ceiling:
                raise ValueError("profile_sdk_step")
            if not finite_number(item) or item * step <= 0:
                raise ValueError("profile_sdk_rate")
    if not isinstance(record["observations"], dict):
        raise ValueError("profile_observations")
    if not isinstance(value["measurements"], list) or any(not isinstance(row, dict) for row in value["measurements"]):
        raise ValueError("profile_measurements")
    for row in value["measurements"]:
        for field in ("duration_s", "distance_m", "angle_rad"):
            number = row.get(field)
            if number is not None and (not finite_number(number) or field == "duration_s" and number <= 0):
                raise ValueError("profile_measurement_" + field)
        if "phase" in row and row["phase"] not in ("acceleration", "steady", "deceleration", "complete", "unknown"):
            raise ValueError("profile_measurement_phase")
        for field in ("status", "outcome"):
            if field in row and row[field] not in ("passed", "failed", "aborted", "unknown"):
                raise ValueError("profile_measurement_outcome")
        if row.get("sdk_step") is not None:
            step = row["sdk_step"]
            minimum, maximum = (1, 180) if row.get("kind") == "turn" else (1, 127)
            if type(step) is not int or not minimum <= abs(step) <= maximum:
                raise ValueError("profile_measurement_sdk_step")
    if record["manual_verified"]:
        error = calibration_status(record, require_mapping=False)
        if error:
            raise ValueError(error)
        if not conditions.get("operator", "").strip() or not conditions.get("date", "").strip():
            raise ValueError("profile_operator_and_date_required")
        if not provenance["notes"].strip() or not value["measurements"]:
            raise ValueError("profile_manual_evidence_required")
        if not any(
            row.get("measurement_id") == record["measurement_id"]
            and isinstance(row.get("notes"), str)
            and row["notes"].strip()
            for row in value["measurements"]
        ):
            raise ValueError("profile_matching_measurement_required")
    _encode(value)
    return value


def profile_digest(profile):
    return hashlib.sha256(_encode(validate_profile(profile))).hexdigest()


def _digest(value):
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError("profile_digest_invalid")
    return value


def _pairs(pairs):
    row = {}
    for key, value in pairs:
        if key in row:
            raise ValueError("profile_duplicate_key")
        row[key] = value
    return row


def _reject_constant(value):
    raise ValueError("profile_number_invalid")


def _read(path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("profile_oversized")
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError("calibration_json_invalid") from None


def read_profile(digest):
    value = validate_profile(_read(storage_dir() / "revisions" / (_digest(digest) + ".json")))
    if profile_digest(value) != digest:
        raise ValueError("profile_content_mismatch")
    return value


@contextmanager
def _lock():
    root = storage_dir()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".catalog.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield root


def _atomic(path, value):
    raw = _encode(value)
    fd, temporary = tempfile.mkstemp(prefix=".calibration-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None  # Rename is the commit point; no fallible cleanup after it.
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass  # Preserve the original failure; a leftover temp is never active.


def _immutable(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".revision-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_encode(value))
            stream.flush()
            os.fsync(stream.fileno())
        # Link exposes complete content atomically, and never overwrites a revision.
        os.link(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _catalog(root):
    path = root / "catalog.json"
    if not path.exists():
        return []
    value = _read(path)
    if not isinstance(value, list) or len(value) > MAX_REVISIONS:
        raise ValueError("profile_catalog_invalid")
    seen = set()
    for row in value:
        if not isinstance(row, dict) or row.get("digest") in seen:
            raise ValueError("profile_catalog_invalid")
        seen.add(_digest(row.get("digest")))
        if not finite_number(row.get("created_at")) or row["created_at"] <= 0:
            raise ValueError("profile_catalog_invalid")
        _text(row.get("name"), "profile_catalog_invalid", limit=80, required=True)
    return value


def list_profiles():
    """Reading an empty catalog creates no directory or process."""
    rows = _catalog(storage_dir())
    result = []
    for row in rows:
        profile = read_profile(row["digest"])
        if row.get("name") != profile["name"]:
            raise ValueError("profile_catalog_mismatch")
        result.append(
            {
                "digest": row["digest"],
                "name": profile["name"],
                "created_at": row["created_at"],
                "provenance": {"kind": profile["provenance"]["kind"]},
                "manual_verified": profile["odometry"]["manual_verified"],
            }
        )
    return result


def save_profile(profile):
    value = validate_profile(profile)
    if value["odometry"]["manual_verified"]:
        error = calibration_status(value["odometry"])
        if error:
            raise ValueError(error)
    digest = profile_digest(value)
    with _lock() as root:
        rows = _catalog(root)
        existing = next((row for row in rows if row["digest"] == digest), None)
        if existing is not None:
            if read_profile(digest) != value:
                raise ValueError("profile_content_mismatch")
            return {"digest": digest, "profile": value, "created": False}
        if len(rows) >= MAX_REVISIONS:
            raise ValueError("profile_catalog_full")
        revisions = root / "revisions"
        revisions.mkdir(exist_ok=True)
        path = revisions / (digest + ".json")
        if path.exists():
            if read_profile(digest) != value:
                raise ValueError("profile_content_mismatch")
        else:
            _immutable(path, value)
        rows.append(
            {
                "digest": digest,
                "name": value["name"],
                "created_at": time.time(),
                "provenance": {"kind": value["provenance"]["kind"]},
                "manual_verified": value["odometry"]["manual_verified"],
            }
        )
        _atomic(root / "catalog.json", rows)
    return {"digest": digest, "profile": value, "created": True}


def read_active(*, include_pending=False):
    path = storage_dir() / "active.json"
    if not path.exists():
        return None
    value = _read(path)
    if (
        not isinstance(value, dict)
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or not finite_number(value.get("activated_at"))
        or value["activated_at"] <= 0
    ):
        raise ValueError("active_profile_invalid")
    if value.get("activation_state") not in ("pending", "applied"):
        raise ValueError("active_profile_state_invalid")
    if set(value) - {
        "schema_version",
        "profile_digest",
        "activated_at",
        "request_id",
        "command_generation",
        "seq",
        "activation_state",
    }:
        raise ValueError("active_profile_invalid")
    if any(key in value for key in ("request_id", "command_generation", "seq")):
        _text(value.get("request_id"), "active_request_id_invalid", limit=128, required=True)
        _text(value.get("command_generation"), "active_generation_invalid", limit=128, required=True)
        if type(value.get("seq")) is not int or not 0 <= value["seq"] < 2**63:
            raise ValueError("active_sequence_invalid")
    read_profile(_digest(value.get("profile_digest")))
    if value["activation_state"] == "pending":
        if not all(key in value for key in ("request_id", "command_generation", "seq")):
            raise ValueError("active_profile_invalid")
        if not include_pending:
            raise ValueError("active_profile_pending")
    return value


def write_active(digest, *, request_id=None, command_generation=None, seq=None, now=None, activation_state="applied"):
    """Sole executor stages pending; explicit applied default preserves local fixtures."""
    read_profile(digest)
    observed = time.time() if now is None else now
    if not finite_number(observed) or observed <= 0:
        raise ValueError("active_timestamp_invalid")
    if activation_state not in ("pending", "applied"):
        raise ValueError("active_profile_state_invalid")
    value = {
        "schema_version": 1,
        "profile_digest": digest,
        "activated_at": observed,
        "activation_state": activation_state,
    }
    if activation_state == "pending" or any(item is not None for item in (request_id, command_generation, seq)):
        _text(request_id, "active_request_id_invalid", limit=128, required=True)
        _text(command_generation, "active_generation_invalid", limit=128, required=True)
        if type(seq) is not int or not 0 <= seq < 2**63:
            raise ValueError("active_sequence_invalid")
        value.update(request_id=request_id, command_generation=command_generation, seq=seq)
    with _lock() as root:
        _atomic(root / "active.json", value)
    return value


def commit_active(digest, *, request_id, command_generation, seq):
    """Commit exactly one staged transaction after the executor's logical apply."""
    _digest(digest)
    _text(request_id, "active_request_id_invalid", limit=128, required=True)
    _text(command_generation, "active_generation_invalid", limit=128, required=True)
    if type(seq) is not int or not 0 <= seq < 2**63:
        raise ValueError("active_sequence_invalid")
    with _lock() as root:
        pending = read_active(include_pending=True)
        expected = {
            "profile_digest": digest,
            "request_id": request_id,
            "command_generation": command_generation,
            "seq": seq,
        }
        if (
            pending is None
            or pending.get("activation_state") != "pending"
            or any(
                type(pending.get(key)) is not type(value) or pending.get(key) != value
                for key, value in expected.items()
            )
        ):
            raise ValueError("active_profile_transaction_mismatch")
        value = dict(pending, activation_state="applied")
        _atomic(root / "active.json", value)
    return value


def validate_activate(row, state, *, now=None):
    """Shared non-actuating intent validation, repeated by the sole executor."""
    now = time.time() if now is None else now
    if not isinstance(row, dict) or not isinstance(state, dict) or not finite_number(now):
        return "activation_metadata_required"
    if (
        type(state.get("contract_version")) is not int
        or state["contract_version"] != 1
        or state.get("state") != "DISARMED"
        or state.get("moving") is not False
        or state.get("stale") is True
    ):
        return "activation_requires_fresh_disarmed"
    observed = state.get("observed_at")
    if not finite_number(observed) or not 0 <= now - observed <= 3:
        return "activation_safety_stale"
    for field in ("target", "output"):
        output = state.get(field)
        if not isinstance(output, dict) or any(
            not finite_number(output.get(key)) or output[key] != 0 for key in ("lx", "az")
        ):
            return "activation_requires_zero_output"
    if (
        not isinstance(row.get("generation"), str)
        or not row["generation"]
        or len(row["generation"]) > 128
        or row["generation"] != state.get("generation")
    ):
        return "stale_generation"
    if row.get("source") != "manual" or type(row.get("seq")) is not int or not 0 <= row["seq"] < 2**63:
        return "activation_metadata_required"
    previous = state.get("last_seq")
    if type(previous) is not int or previous < -1 or row["seq"] <= previous:
        return "activation_sequence_replayed"
    if not isinstance(row.get("request_id"), str) or not row["request_id"].strip() or len(row["request_id"]) > 128:
        return "request_id_required"
    ts, ttl = row.get("ts"), row.get("ttl_ms")
    if not finite_number(ts) or not finite_number(ttl) or not 0 < ttl <= 500 or not 0 <= now - ts <= ttl / 1000:
        return "activation_expired"
    if (
        row.get("operator_consent") is not True
        or not isinstance(row.get("operator_plan"), str)
        or not row["operator_plan"].strip()
        or len(row["operator_plan"]) > 4096
    ):
        return "activation_operator_plan_required"
    if row.get("action", "activate_calibration") != "activate_calibration":
        return "activation_action_invalid"
    try:
        _digest(row.get("profile_digest"))
    except ValueError:
        return "profile_digest_invalid"
    return None


def _fresh(row, now):
    return (
        isinstance(row, dict)
        and finite_number(row.get("observed_at"))
        and 0 <= now - row["observed_at"] <= 3
        and row.get("stale") is not True
        and row.get("offline") is not True
    )


def _calibration(row):
    value = row.get("calibration") if isinstance(row, dict) else None
    return value if isinstance(value, dict) else {}


def _matches_ack(ack, active, motion, now):
    return (
        isinstance(ack, dict)
        and ack.get("accepted") is True
        and ack.get("status") == "executed"
        and ack.get("action") == "activate_calibration"
        and ack.get("source") == "manual"
        and ack.get("actuation") is False
        and not ack.get("error")
        and ack.get("profile_digest") == active["profile_digest"]
        and isinstance(active.get("request_id"), str)
        and ack.get("request_id") == active["request_id"]
        and isinstance(active.get("command_generation"), str)
        and ack.get("command_generation") == active["command_generation"]
        and type(active.get("seq")) is int
        and ack.get("seq") == active["seq"]
        and isinstance(_calibration(motion).get("applied_generation"), str)
        and bool(_calibration(motion)["applied_generation"])
        and ack.get("generation") == _calibration(motion)["applied_generation"]
        and ack.get("instance_id") == motion.get("instance_id")
        and finite_number(ack.get("observed_at"))
        and active["activated_at"] <= ack["observed_at"] <= now
    )


def profile_confirmation(active, motion, odometry, now):
    """Pure proof shared by configuration status and manual-reference admission."""
    if not isinstance(active, dict) or active.get("activation_state") != "applied":
        return "unconfirmed"
    mc, oc = _calibration(motion), _calibration(odometry)
    if (
        not _fresh(motion, now)
        or not _fresh(odometry, now)
        or not _fresh(mc, now)
        or not _fresh(oc, now)
        or mc.get("profile_digest") != active["profile_digest"]
        or oc.get("profile_digest") != active["profile_digest"]
        or mc.get("error")
        or oc.get("error")
        or not isinstance(motion.get("instance_id"), str)
        or not motion["instance_id"]
        or mc.get("instance_id") != motion["instance_id"]
        or oc.get("motion_instance_id") != motion["instance_id"]
    ):
        return "unconfirmed"
    if (
        mc.get("source") == oc.get("source") == "saved_profile"
        and mc.get("activation_request_id") is None
        and oc.get("activation_request_id") is None
        and mc.get("applied_ack") is None
        and mc.get("applied_generation") is None
        and oc.get("applied_generation") is None
    ):
        return "loaded_from_saved"
    if (
        _matches_ack(mc.get("applied_ack"), active, motion, now)
        and mc.get("activation_request_id") == active["request_id"]
        and oc.get("activation_request_id") == active["request_id"]
        and mc.get("command_generation") == active["command_generation"]
        and oc.get("command_generation") == active["command_generation"]
        and oc.get("seq") == active["seq"]
        and oc.get("applied_generation") == mc.get("applied_generation")
    ):
        return "executed"
    return "unconfirmed"
