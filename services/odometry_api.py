"""Read-only pose/reference projection and explicit non-actuating reference intent."""

import json
import time

from flask import jsonify, request

from apps.motion.calibration_profiles import profile_confirmation, read_active
from apps.odometry.reference import reference_paths, validate_reference
from apps.safety.state import read_status
from common.bus import BusPub
from common.data_quality import confirmed_home, finite_number

_publisher = None
wall_clock = time.time


def snapshot():
    path, _ = reference_paths()
    try:
        if path.stat().st_size > 65536:
            raise ValueError("status_oversized")
        value = json.loads(path.read_text(encoding="utf-8"))
        observed = value.get("observed_at") if isinstance(value, dict) else None
        if not finite_number(observed) or not 0 <= wall_clock() - observed <= 3.0:
            raise ValueError("status_stale")
        started = value.get("started_at")
        pose = value.get("pose")
        if (
            type(value.get("contract_version")) is not int
            or value["contract_version"] != 1
            or not isinstance(value.get("instance_id"), str)
            or not value["instance_id"]
            or not finite_number(started)
            or not 0 < started <= observed
            or type(value.get("reference_verified")) is not bool
            or value.get("actuation") is not False
            or not isinstance(pose, dict)
            or not all(finite_number(pose.get(key)) for key in ("x", "y", "theta"))
            or type(pose.get("data_ready")) is not bool
            or type(pose.get("navigation_ready")) is not bool
        ):
            raise ValueError("invalid_process_status")
        reference = value.get("reference_id")
        if (
            value["reference_verified"]
            and (not isinstance(reference, str) or not reference)
            or not value["reference_verified"]
            and reference is not None
        ):
            raise ValueError("invalid_reference_status")
        if value.get("last_ack") is not None and not isinstance(value["last_ack"], dict):
            raise ValueError("invalid_ack_status")
        home = value.get("home")
        if home is not None:
            if (
                not isinstance(home, dict)
                or not value["reference_verified"]
                or home.get("operator_confirmed") is not True
                or home.get("reference_id") != reference
                or home.get("calibration_id") != pose.get("calibration_id")
                or not all(finite_number(home.get(key)) for key in ("x", "y"))
                or home != pose.get("home")
            ):
                raise ValueError("invalid_home_status")
        if pose["navigation_ready"] and confirmed_home(pose) is None:
            raise ValueError("invalid_navigation_home")
        return value
    except (OSError, ValueError, TypeError):
        return {
            "contract_id": "rider.odometry",
            "contract_version": 1,
            "reference_verified": False,
            "reference_id": None,
            "home": None,
            "last_ack": None,
            "observed_at": None,
            "error": "odometry_unavailable",
            "actuation": False,
        }


def reference_state():
    return jsonify(snapshot())


def _profile_error(row, state, current):
    expected = row.get("profile_digest")
    config = state.get("calibration")
    model = current.get("calibration")
    motion_digest = config.get("profile_digest") if isinstance(config, dict) else None
    odometry_digest = model.get("profile_digest") if isinstance(model, dict) else None
    if expected is None and motion_digest is None and odometry_digest is None:
        return None  # Existing explicit legacy-file references remain supported.
    try:
        active = read_active()
        if active is None or active["profile_digest"] != expected:
            return "reference_profile_unconfirmed"
        if profile_confirmation(active, state, current, wall_clock()) == "unconfirmed":
            return "reference_profile_unconfirmed"
    except (OSError, ValueError, KeyError, TypeError):
        return "reference_profile_unavailable"
    return None


def operator_reference():
    row = request.get_json(silent=True)
    state = read_status()
    error = validate_reference(row, state, now=wall_clock())
    if error:
        return jsonify({"accepted": False, "error": error, "actuation": False}), 409
    current = snapshot()
    if current.get("error"):
        return jsonify({"accepted": False, "error": current["error"], "actuation": False}), 503
    state = read_status()
    error = validate_reference(row, state, now=wall_clock(), started_at=current.get("started_at"))
    error = error or _profile_error(row, state, current)
    if error:
        return jsonify({"accepted": False, "error": error, "actuation": False}), 409
    global _publisher
    try:
        if _publisher is None:
            _publisher = BusPub()
        _publisher.publish("odometry.reference", row, add_ts=False)
    except Exception:
        _publisher = None
        return jsonify({"accepted": False, "error": "reference_transport_failed", "actuation": False}), 503
    return jsonify(
        {
            "status": "pending",
            "request_id": row["request_id"],
            "generation": row["generation"],
            "source": row["source"],
            "seq": row["seq"],
            "profile_digest": row.get("profile_digest"),
            "actuation": False,
            "physical_completion": "unverified",
        }
    ), 202
