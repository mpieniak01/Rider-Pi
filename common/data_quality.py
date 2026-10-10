"""Small source-time checks shared by physical data consumers; no I/O."""

from __future__ import annotations

import math
import time


def finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def sample_status(payload, *, max_age_s, now=None, previous_ts=None):
    now = time.time() if now is None else now
    result = {"ready": False, "error": "missing_sample", "observed_at": None, "age_s": None}
    if not isinstance(payload, dict):
        return result
    observed = payload.get("observed_at")
    if not finite_number(now) or not finite_number(max_age_s) or max_age_s <= 0:
        return dict(result, error="invalid_quality_budget")
    if not finite_number(observed) or observed <= 0:
        return dict(result, error="invalid_source_time")
    age = now - observed
    result.update(observed_at=observed, age_s=max(0.0, age))
    if age < 0 or age > max_age_s:
        return dict(result, error="sample_stale_or_future")
    if finite_number(previous_ts) and observed < previous_ts:
        return dict(result, error="sample_out_of_order")
    if any(payload.get(key) is True for key in ("stale", "offline")) or payload.get("error"):
        return dict(result, error="sample_reports_failure")
    if any(payload.get(key) is False for key in ("valid", "data_ready")):
        return dict(result, error="sample_unverified")
    return dict(result, ready=True, error=None)


def pose_status(payload, *, max_age_s=0.5, now=None, previous_ts=None):
    status = sample_status(payload, max_age_s=max_age_s, now=now, previous_ts=previous_ts)
    if not status["ready"]:
        return status
    if not all(finite_number(payload.get(key)) for key in ("x", "y", "theta")):
        return dict(status, ready=False, error="invalid_pose")
    if (
        payload.get("navigation_ready") is not True
        or frame_identity(payload) is None
        or confirmed_home(payload) is None
    ):
        return dict(status, ready=False, error="pose_uncalibrated_or_unverified")
    confidence = payload.get("confidence")
    if confidence is not None and (not finite_number(confidence) or not 0 < confidence <= 1):
        return dict(status, ready=False, error="pose_confidence_unknown")
    return status


def frame_identity(payload):
    """A calibrated coordinate frame belongs to one current manual reference."""
    if not isinstance(payload, dict):
        return None
    values = tuple(payload.get(key) for key in ("calibration_id", "reference_id"))
    return values if all(isinstance(value, str) and value.strip() for value in values) else None


def confirmed_home(payload):
    if not isinstance(payload, dict) or frame_identity(payload) is None:
        return None
    home = payload.get("home")
    if (
        not isinstance(home, dict)
        or home.get("operator_confirmed") is not True
        or frame_identity(home) != frame_identity(payload)
        or not all(finite_number(home.get(key)) for key in ("x", "y"))
    ):
        return None
    return home["x"], home["y"]
