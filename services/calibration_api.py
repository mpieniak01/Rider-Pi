"""Local profile API; transport acceptance never proves runtime or physical readiness."""

from __future__ import annotations

import json
import threading
import time

from flask import jsonify, request

from apps.motion import calibration_profiles as profiles
from apps.safety.state import read_status
from common.bus import BusPub
from services.api_core.static_pages import serve_web
from services.odometry_api import snapshot as odometry_snapshot

wall_clock = time.time
_transport = threading.local()
_lock = threading.Lock()
_pending = None


_fresh = profiles._fresh
_calibration = profiles._calibration
_confirmation = profiles.profile_confirmation


def snapshot():
    now = wall_clock()
    motion, odometry = read_status(), odometry_snapshot()
    oc = _calibration(odometry)
    result = {
        "contract_id": "rider.calibration",
        "contract_version": 1,
        "schema_version": 1,
        "server_time": now,
        "motion": motion,
        "odometry": odometry,
        "active": None,
        "requested": None,
        "status": "unknown",
        "error": None,
        "confirmation": "unconfirmed",
        "stale": not (_fresh(motion, now) and _fresh(odometry, now)),
        "model_ready": False,
        "calibration_error": oc.get("odometry_error"),
        "actuation": False,
        "physical_completion": "unverified",
    }
    try:
        active = profiles.read_active(include_pending=True)
    except (ValueError, OSError):
        result["error"] = "active_profile_unavailable"
        return result
    result["active"] = active
    if active is None:
        result["status"] = "unknown" if not _fresh(motion, now) else "unconfigured"
    else:
        result["confirmation"] = _confirmation(active, motion, odometry, now)
        result["status"] = "partial" if result["confirmation"] == "unconfirmed" else "applied"
        if result["status"] == "partial":
            result["error"] = (
                "active_profile_pending"
                if active["activation_state"] == "pending"
                else "profile_not_confirmed_by_both_processes"
            )
        result["model_ready"] = bool(
            result["status"] == "applied" and oc.get("model_ready") is True and not result["calibration_error"]
        )
    with _lock:
        pending = dict(_pending) if _pending else None
    result["requested"] = pending
    if pending and not (active and active.get("request_id") == pending["request_id"] and result["status"] == "applied"):
        ack = _calibration(motion).get("last_ack")
        rejected = (
            _fresh(motion, now)
            and isinstance(ack, dict)
            and ack.get("request_id") == pending["request_id"]
            and ack.get("profile_digest") == pending["profile_digest"]
            and ack.get("accepted") is False
            and ack.get("command_generation") == pending["generation"]
            and ack.get("seq") == pending["seq"]
        )
        if rejected:
            result.update(
                status="partial",
                error=ack.get("error") or ack.get("reason") or "activation_rejected",
                confirmation="unconfirmed",
                model_ready=False,
            )
        elif active and active["activation_state"] == "pending":
            result.update(
                status="partial", error="active_profile_pending", confirmation="unconfirmed", model_ready=False
            )
        elif now - pending["ts"] <= 5:
            result.update(status="pending", error=None, confirmation="unconfirmed", model_ready=False)
        else:
            result.update(
                status="partial", error="activation_confirmation_timeout", confirmation="unconfirmed", model_ready=False
            )
    return result


def state():
    return jsonify(snapshot())


def page():
    return serve_web("calibration.html")


def _error(code, status):
    return jsonify({"error": code, "accepted": False, "actuation": False}), status


def _body():
    if not request.is_json:
        raise ValueError("json_required")
    raw = request.stream.read(profiles.MAX_BYTES + 1025)
    if len(raw) > profiles.MAX_BYTES + 1024:
        raise ValueError("request_oversized")
    try:
        row = json.loads(raw, object_pairs_hook=profiles._pairs, parse_constant=profiles._reject_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError("invalid_json") from None
    if not isinstance(row, dict):
        raise ValueError("object_required")
    return row


def catalog():
    if request.method == "GET":
        try:
            return jsonify({"schema_version": 1, "profiles": profiles.list_profiles(), "actuation": False})
        except (ValueError, OSError):
            return _error("profile_catalog_unavailable", 503)
    try:
        row = _body()
        if set(row) - {"profile", "imported"} or "profile" not in row or type(row.get("imported", False)) is not bool:
            raise ValueError("profile_request_invalid")
        profile = row["profile"]
        if row.get("imported"):
            if not isinstance(profile, dict) or not isinstance(profile.get("provenance"), dict):
                raise ValueError("profile_schema")
            profile = dict(profile, provenance=dict(profile["provenance"], kind="historical"))
        saved = profiles.save_profile(profile)
        return jsonify(dict(saved, ok=True, persisted=True, actuation=False)), 201 if saved["created"] else 200
    except ValueError as exc:
        return _error(str(exc), 400)
    except BlockingIOError:
        return _error("calibration_busy", 409)
    except OSError:
        return _error("profile_storage_unavailable", 503)


def profile(digest):
    try:
        return jsonify({"digest": digest, "profile": profiles.read_profile(digest), "actuation": False})
    except FileNotFoundError:
        return _error("profile_not_found", 404)
    except ValueError as exc:
        return _error(str(exc), 400)
    except OSError:
        return _error("profile_storage_unavailable", 503)


def _publish(row):
    publisher = getattr(_transport, "publisher", None)
    if publisher is None:
        publisher = BusPub(warmup_ms=10)
        _transport.publisher = publisher
    try:
        publisher.publish("calibration.activate", row, add_ts=False)
    except Exception:
        publisher.close()
        _transport.publisher = None
        raise


def activate():
    global _pending
    try:
        row = _body()
        if set(row) - {
            "profile_digest",
            "request_id",
            "generation",
            "seq",
            "source",
            "ts",
            "ttl_ms",
            "operator_consent",
            "operator_plan",
            "action",
        }:
            raise ValueError("activation_fields_invalid")
        motion = read_status()
        error = profiles.validate_activate(row, motion, now=wall_clock())
        if error:
            return _error(error, 409)
        profiles.read_profile(row["profile_digest"])
        odometry = odometry_snapshot()
        if (
            not _fresh(odometry, wall_clock())
            or odometry.get("error")
            or not isinstance(odometry.get("instance_id"), str)
            or not odometry["instance_id"]
        ):
            return _error("odometry_unavailable", 503)
        row = dict(row, action="activate_calibration")
        with _lock:
            error = profiles.validate_activate(row, read_status(), now=wall_clock())
            if error:
                return _error(error, 409)
            _publish(row)
            _pending = {key: row[key] for key in ("profile_digest", "request_id", "generation", "seq", "source", "ts")}
            pending = dict(_pending)
        return jsonify(
            dict(
                pending,
                status="pending",
                accepted=False,
                pending=True,
                actuation=False,
                physical_completion="unverified",
            )
        ), 202
    except ValueError as exc:
        return _error(str(exc), 400)
    except FileNotFoundError:
        return _error("profile_not_found", 404)
    except Exception:
        return _error("activation_transport_or_storage_failed", 503)


def controls():
    from apps.motion import manual_settings

    def idle():
        motion = read_status()
        if not profiles._fresh(motion, wall_clock()):
            raise ValueError("motion_status_unavailable")
        if (
            motion.get("state") not in {"DISARMED", "ARMED"}
            or motion.get("moving") is not False
            or motion.get("deadline", 0)
            or any((motion.get("output") or {}).values())
            or any((motion.get("target") or {}).values())
        ):
            raise ValueError("manual_settings_requires_idle")

    try:
        if request.method == "POST":
            row = _body()
            if set(row) - {"revision", "values", "directions", "profile"} or not {"revision", "values"} <= set(row):
                raise ValueError("manual_settings_request")
            if "profile" in row:
                manual_settings.manage_profile(
                    row["profile"],
                    row["revision"],
                    patch=row["values"],
                    directions=row.get("directions"),
                    validate_state=idle,
                )
            else:
                manual_settings.update(
                    row["values"], row["revision"], directions=row.get("directions"), validate_state=idle
                )
        return jsonify(dict(manual_settings.snapshot(), ok=True))
    except ValueError as exc:
        code = str(exc)
        status = (
            409
            if code in {"manual_settings_conflict", "motion_status_unavailable", "manual_settings_requires_idle"}
            else 400
        )
        return _error(code, status)
    except (OSError, TypeError):
        return _error("manual_settings_unavailable", 503)
