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

from apps.motion.calibration_schema import (
    MAX_BYTES as MAX_BYTES,
    MAX_MEASUREMENTS as MAX_MEASUREMENTS,
    _bounded as _bounded,
    _encode as _encode,
    _fields as _fields,
    _text as _text,
    validate_profile as validate_profile,
)
from apps.odometry.calibration import calibration_status as calibration_status
from common.data_quality import finite_number

MAX_REVISIONS = 64
ACTIVE_PROFILE_FILENAME = "active.json"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def storage_dir():
    default = Path(__file__).resolve().parents[2] / "config" / "local" / "motion-calibration"
    override = os.getenv("RIDER_CALIBRATION_DIR")
    value = Path(override) if override else default
    if not value.is_absolute():
        raise ValueError("calibration_directory_must_be_absolute")
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
    except (ValueError, RecursionError):
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
    path = storage_dir() / ACTIVE_PROFILE_FILENAME
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
        _atomic(root / ACTIVE_PROFILE_FILENAME, value)
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
        _atomic(root / ACTIVE_PROFILE_FILENAME, value)
    return value


def _activation_metadata_error(row, state):
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
    return None


def _activation_state_error(state, now):
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
    return None


def validate_activate(row, state, *, now=None):
    """Shared non-actuating intent validation, repeated by the sole executor."""
    now = time.time() if now is None else now
    if not isinstance(row, dict) or not isinstance(state, dict) or not finite_number(now):
        return "activation_metadata_required"
    error = _activation_state_error(state, now)
    if error:
        return error
    error = _activation_metadata_error(row, state)
    if error:
        return error
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
