#!/usr/bin/env python3
"""One manual actuator attempt; never invoked by pytest, CI or diagnostics."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
import uuid


def require_operator():
    if os.getenv("CI") or os.getenv("RIDER_TEST_ISOLATED") == "1":
        raise RuntimeError("Physical probes forbidden in automated runs.")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("Present operator and interactive terminal required.")


def request_json(base, path, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode(errors="replace")) from exc
    if payload is not None and (result.get("ok") is not True or result.get("confirmed") is not True):
        raise RuntimeError("Executor did not confirm: " + json.dumps(result))
    return result


def context(snapshot):
    if snapshot.get("contract_version") != 1 or snapshot.get("stale") or not snapshot.get("generation"):
        raise RuntimeError("Fresh safety contract v1 required.")
    return {
        "generation": snapshot["generation"],
        "seq": int(snapshot.get("last_seq", -1)) + 1,
        "ts": time.time(),
        "ttl_ms": 500,
        "source": "manual",
        "execution_context": "test",
        "test_operator_consent": True,
    }


def _validate_attempt(args):
    if not args.plan.strip() or len(args.plan) > 512:
        raise ValueError("Specific plan of at most 512 characters required.")
    if not all(math.isfinite(v) for v in (args.vx, args.yaw, args.duration)):
        raise ValueError("Finite values required.")
    if not -1 <= args.vx <= 1 or not -1 <= args.yaw <= 1 or not 0.01 <= args.duration <= 0.25:
        raise ValueError("Speed [-1,1], duration 0.01..0.25 seconds required.")
    if args.action == "height" and (args.height is None or not 75 <= args.height <= 115):
        raise ValueError("Explicit height 75..115 required.")
    if args.action == "balance" and args.enabled is None:
        raise ValueError("Explicit balance setting required.")
    if args.action == "action" and args.action_id is None:
        raise ValueError("Explicit action-id required.")


def _require_capability(snapshot, action):
    capability = snapshot.get("capabilities", {}).get(action, {})
    if not capability.get("available") or (action != "height" and not capability.get("stop_verified")):
        raise RuntimeError("Unavailable or uncharacterized capability: " + json.dumps(capability))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    parser.add_argument("--action", required=True, choices=("move", "turn", "height", "balance", "action"))
    parser.add_argument("--plan", required=True, help="Attempt, floor, clear space, cable, STOP method")
    parser.add_argument("--vx", type=float, default=0)
    parser.add_argument("--yaw", type=float, default=0)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--height", type=int)
    parser.add_argument("--enabled", choices=("true", "false"))
    parser.add_argument("--action-id", type=int)
    args = parser.parse_args()
    try:
        require_operator()
        _validate_attempt(args)
        snapshot = request_json(args.api, "/api/control/state")["safety"]
        if snapshot.get("state") != "DISARMED":
            raise RuntimeError("DISARMED required; never clear ESTOP automatically.")
        _require_capability(snapshot, args.action)
        token = uuid.uuid4().hex[:8]
        command = {
            "action": args.action,
            "vx": args.vx,
            "yaw": args.yaw,
            "duration": args.duration,
            "height": args.height,
            "enabled": args.enabled == "true",
            "action_id": args.action_id,
        }
        print("Plan:", args.plan)
        print("One attempt:", json.dumps(command))
        print("Confirm clear space, stable floor, cable clearance, reachable STOP.")
        if input("Type ZGODA " + token + ": ").strip() != "ZGODA " + token:
            raise RuntimeError("No operator approval.")
        attempted = False
        try:
            arm = context(snapshot)
            arm.update(
                action="arm",
                owner="manual",
                lease_s=5,
                operator_consent=True,
                operator_plan=args.plan,
                request_id="arm-" + token,
            )
            attempted = True
            request_json(args.api, "/api/safety", arm)
            snapshot = request_json(args.api, "/api/control/state")["safety"]
            command.update(
                context(snapshot),
                request_id="probe-" + token,
                settings_revision=snapshot["manual_settings"]["revision"],
            )
            result = request_json(args.api, "/api/control", command)
            print(json.dumps(result, ensure_ascii=False))
            print("SDK acknowledgement does not verify physical completion.")
            time.sleep(args.duration)
        finally:
            if attempted:
                print("STOP:", json.dumps(request_json(args.api, "/api/safety", {"action": "stop"})))
    except (RuntimeError, ValueError, KeyError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
