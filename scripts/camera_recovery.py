#!/usr/bin/env python3
"""Explicit camera recovery through the same guarded resource implementation."""

from __future__ import annotations

import argparse
import json
import re

from services.api_core import resource_diag


def recover(paths: list[str], pids: list[int], *, force: bool, operator_consent: bool) -> dict:
    if not paths or any(not re.fullmatch(r"/dev/video\d+", path) for path in paths):
        return {"ok": False, "error": "exact_v4l2_paths_required"}
    observed = resource_diag.inspect("camera")
    owners = [row for row in observed.get("holders", []) if row.get("path") in paths]
    plan = {
        "paths": paths,
        "owners": owners,
        "pids": pids,
        "effects": ["SIGTERM to selected observed V4L2 owners; no SPI/LCD, SIGKILL or restart"],
    }
    if not force or not operator_consent or not pids:
        return {"ok": False, "error": "manual_recovery_confirmation_required", **plan}
    if observed.get("state") in {"unknown", "unavailable"} or observed.get("error"):
        return {"ok": False, "error": "ownership_unknown", **plan}
    if any(
        isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1 or pid not in {row.get("pid") for row in owners}
        for pid in pids
    ):
        return {"ok": False, "error": "owner_mismatch_or_protected", **plan}
    return resource_diag.release("camera", limit_pids=pids, force=True, operator_consent=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--extra", action="append", default=[])
    parser.add_argument("--pid", type=int, action="append", default=[])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--operator-consent", action="store_true")
    args = parser.parse_args()
    result = recover([args.device, *args.extra], args.pid, force=args.force, operator_consent=args.operator_consent)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result.get("ok") else 3)


if __name__ == "__main__":
    main()
