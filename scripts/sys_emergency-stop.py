#!/usr/bin/env python3
"""Canonical E-Stop; clearing requires a fresh operator-approved plan."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("on", "off", "stop", "status"))
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    parser.add_argument("--plan")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("manual_probe", Path(__file__).with_name("manual_motion-probe.py"))
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    try:
        if args.action == "status":
            result = probe.request_json(args.api, "/api/control/state")
        elif args.action == "off":
            probe.require_operator()
            if not args.plan or not args.plan.strip():
                raise RuntimeError("Specific plan required to clear ESTOP.")
            snapshot = probe.request_json(args.api, "/api/control/state")["safety"]
            print("Clear ESTOP, remain DISARMED. Plan:", args.plan)
            if input("Type CLEAR ESTOP: ").strip() != "CLEAR ESTOP":
                raise RuntimeError("No operator consent.")
            command = probe.context(snapshot)
            command.update(action="clear_estop", operator_consent=True, operator_plan=args.plan)
            result = probe.request_json(args.api, "/api/safety", command)
        else:
            result = probe.request_json(args.api, "/api/safety", {"action": "estop" if args.action == "on" else "stop"})
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (RuntimeError, KeyError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
