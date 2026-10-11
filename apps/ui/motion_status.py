"""Read-only display projection of safety v1; no physical motion inference."""

from __future__ import annotations

import time

from common.observations import finite, source_time


def display_motion(row, *, now=None):
    row = row if isinstance(row, dict) else {}
    now = time.time() if now is None else now
    at = source_time(row.get("observed_at"))
    current = (
        row.get("contract_version") == 1
        and row.get("state") in {"ARMED", "DISARMED", "ESTOP"}
        and at is not None
        and finite(now)
        and 0 <= now - at <= 3
        and row.get("stale") is not True
        and row.get("offline") is not True
    )
    output = row.get("output") if isinstance(row.get("output"), dict) else {}
    return {
        "state": row.get("state") if current else "UNKNOWN",
        "current": current,
        "moving": row.get("moving") if current and type(row.get("moving")) is bool else None,
        "can_move": current and row.get("can_move") is True,
        "observed_at": at,
        "output": {axis: output.get(axis) if current and finite(output.get(axis)) else None for axis in ("lx", "az")},
        "output_unit": "normalized",
        "physical_completion": "unverified",
    }


def number_label(value):
    return f"{value:.2f}" if finite(value) else "—"
