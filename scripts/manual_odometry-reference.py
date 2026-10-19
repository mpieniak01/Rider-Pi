#!/usr/bin/env python3
"""Operator-confirmed reference for the running odometry process; no actuator API."""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid


def call(base, path, payload=None):
    data = None if payload is None else json.dumps(payload, allow_nan=False).encode()
    request = urllib.request.Request(base.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=2.0) as response:
        return json.load(response)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--x", type=float, required=True)
    parser.add_argument("--y", type=float, required=True)
    parser.add_argument("--theta", type=float, required=True, help="Current heading in radians, CCW positive")
    parser.add_argument("--home-x", type=float, help="Independently checked HOME X in the same reference frame")
    parser.add_argument("--home-y", type=float, help="Independently checked HOME Y in the same reference frame")
    options = parser.parse_args(argv)
    if (options.home_x is None) != (options.home_y is None):
        parser.error("HOME requires both --home-x and --home-y, or neither")
    if os.getenv("CI") or os.getenv("RIDER_TEST_ISOLATED") or not sys.stdin.isatty():
        parser.error("Manual reference requires an operator terminal outside CI/test isolation")
    safety = call(options.api, "/api/safety")
    safety = safety.get("safety", safety)
    if safety.get("state") != "DISARMED" or safety.get("ready") is not True:
        parser.error("Reference requires confirmed DISARMED with valid telemetry")
    print("Confirm the robot is stationary at the recorded reference. Plan: " + options.plan)
    if options.home_x is not None:
        print(f"Also confirm the independently observed HOME coordinate: ({options.home_x}, {options.home_y})")
    if input("Type REFERENCE to confirm this one observation: ").strip() != "REFERENCE":
        return 1
    sequence = max(time.time_ns(), safety.get("last_seq", -1) + 1)
    row = {
        "generation": safety["generation"],
        "source": "manual",
        "seq": sequence,
        "request_id": uuid.uuid4().hex,
        "ts": time.time(),
        "ttl_ms": 500,
        "operator_consent": True,
        "operator_plan": options.plan,
        "x": options.x,
        "y": options.y,
        "theta": options.theta,
        "home_operator_confirmed": options.home_x is not None,
        "home_x": options.home_x,
        "home_y": options.home_y,
    }
    print(json.dumps(call(options.api, "/api/odometry/reference", row), ensure_ascii=False))
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        status = call(options.api, "/api/odometry/state")
        ack = status.get("last_ack") or {}
        if (
            all(ack.get(key) == row[key] for key in ("request_id", "source", "seq"))
            and ack.get("command_generation") == row["generation"]
            and ack.get("observed_at", 0) >= row["ts"]
        ):
            print(json.dumps(ack, ensure_ascii=False))
            return 0 if ack.get("status") == "executed" else 1
        time.sleep(0.1)
    print("No matching reference ACK; reference remains unconfirmed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
