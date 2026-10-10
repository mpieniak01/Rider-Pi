#!/usr/bin/env python3
"""Verify that offload consumes the existing feed rather than taking V4L2."""

from __future__ import annotations

import json
import sys

from common import systemd_ctrl
from services.api_core import resource_diag


def check(action: str) -> dict:
    if action not in {"claim", "release"}:
        return {"ok": False, "error": "claim_or_release_required"}
    if action == "release":
        row = systemd_ctrl.status("rider-vision-offload.service")
        return {
            "ok": row.get("active") == "inactive" and not row.get("error"),
            "status": row,
            "effects": [],
            "hint": "Task leases decide whether the feed can stop.",
        }
    observed = resource_diag.inspect("camera")
    feed = systemd_ctrl.status("frame-distributor.service")
    owners = observed.get("holders", [])
    valid = (
        observed.get("state") not in {"unknown", "unavailable"}
        and bool(owners)
        and all(owner.get("service") == "camera-capture@raw.service" for owner in owners)
        and feed.get("active") == "active"
        and not feed.get("error")
    )
    return {
        "ok": valid,
        "resource": observed,
        "feed": feed,
        "effects": [],
        "error": None if valid else "raw_feed_owner_unconfirmed",
    }


if __name__ == "__main__":
    result = check(sys.argv[1]) if len(sys.argv) == 2 else {"ok": False, "error": "claim_or_release_required"}
    print(json.dumps(result))
    sys.exit(0 if result.get("ok") else 3)
