"""One camera activity projection: intent, processes and frames stay distinct."""

from __future__ import annotations

import sys
import time

from common.observations import source_time
from common.service_catalog import CAMERA_CAPTURE_UNITS
from common.systemd_ctrl import status


def snapshot(*, heartbeat=None, owners=None, consumers=(), status_fn=None, now=None):
    status_fn = status if status_fn is None else status_fn
    if owners is None:
        from services.core.resource_observation import snapshot as observe_resource

        owners = observe_resource("camera")
    now = time.time() if now is None else now
    if heartbeat is None:
        module = sys.modules.get("services.api_core.compat")
        heartbeat = getattr(module, "LAST_CAMERA", {}) if module else {}
    at = source_time(heartbeat.get("ts"))
    age = now - at if type(at) in (int, float) else None
    data_fresh = age is not None and 0 <= age <= 5
    rows = [status_fn(unit) for unit in sorted(CAMERA_CAPTURE_UNITS)]
    known = all(
        row.get("active") in {"active", "inactive", "failed"} and not row.get("stale") and not row.get("error")
        for row in rows
    )
    running = any(row.get("active") == "active" and not row.get("stale") and not row.get("error") for row in rows)
    occupied = (
        owners is not None and owners.get("free") is False and not owners.get("error") and bool(owners.get("holders"))
    )
    released = owners is not None and owners.get("free") is True and not owners.get("error")
    on = True if running or occupied else False if known and released else None
    return {
        "on": on,
        "source": "camera/systemd+heartbeat",
        "observed_at": now,
        "consumers": list(consumers),
        "service_running": True if running else False if known else None,
        "data_fresh": data_fresh,
        "frame_observed_at": at if age is not None else None,
        "age_s": round(age, 3) if age is not None else None,
        "fps": heartbeat.get("fps") if data_fresh else None,
        "mode": heartbeat.get("mode"),
        "services": rows,
        "status_basis": "process_and_ownership",
        "error": (owners.get("error") or "camera_status_unavailable") if on is None else None,
        "physical_validity": "unverified",
    }
