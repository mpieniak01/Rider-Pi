#!/usr/bin/env python3
"""Public goal client. State and all service decisions belong to the Rider API."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.api_client import APIClient, APIError


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status"])
    parser.add_argument("feature", nargs="?")
    parser.add_argument("--direct", action="store_true", help="Local emergency transport; use when API is stopped")
    parser.add_argument("--url", help="Serving Rider API; default RIDER_API_URL or localhost:8080")
    parser.add_argument("--options", default="{}", help="Goal options as JSON, validated by the API")
    parser.add_argument("--control-file", type=Path, help="Original operator envelope; moving starts require a TTY")
    parser.add_argument("--seconds", type=int, help="Foreground passive session, stopped on timeout or interruption")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        if args.direct:
            from common.local_api_client import LocalAPIClient

            client = LocalAPIClient(args.url)
        else:
            client = APIClient(args.url)
        if args.action == "status":
            response = client.request("/api/logic/catalog")
        else:
            if not args.feature:
                raise ValueError("feature_required")
            options = json.loads(args.options)
            if not isinstance(options, dict):
                raise ValueError("options_object_required")
            body = {"enabled": args.action == "start", "options": options}
            if body["enabled"]:
                catalog = client.catalog()
                feature = next(
                    (
                        row
                        for row in catalog["features"]
                        if args.feature == row["name"] or args.feature in row.get("aliases", [])
                    ),
                    None,
                )
                if feature is None:
                    raise ValueError("unknown_feature")
                if type(feature.get("can_move")) is not bool:
                    raise ValueError("unknown_motion_effect")
                if args.seconds is not None and feature.get("requested"):
                    raise ValueError("timed_session_requires_unrequested_goal")
                if feature["can_move"]:
                    if not sys.stdin.isatty() or args.control_file is None:
                        raise ValueError("moving_start_requires_operator_tty_and_control_file")
                    if args.seconds is not None:
                        raise ValueError("timed_cli_session_is_passive_only")
                if args.control_file is not None:
                    if args.control_file.stat().st_size > 65536:
                        raise ValueError("control_file_oversized")
                    control = json.loads(args.control_file.read_text())
                    if not isinstance(control, dict):
                        raise ValueError("control_object_required")
                    # Keep original generation, sequence, timestamp and TTL.
                    body.update(control)
                    body.update(enabled=True, options=options)
            elif args.seconds is not None:
                raise ValueError("seconds_requires_start")
            if args.seconds is not None and not 1 <= args.seconds <= 300:
                raise ValueError("seconds_must_be_1_to_300")
            path = "/api/logic/feature/" + quote(args.feature, safe="")
            response = client.request(path, "POST", body)
            if args.seconds is not None:
                if (response.get("data", {}).get("result") or {}).get("idempotent"):
                    raise ValueError("timed_session_does_not_own_goal")
                from threading import Event

                previous = signal.getsignal(signal.SIGTERM)
                finished = Event()
                signal.signal(signal.SIGTERM, lambda *_: finished.set())
                try:
                    print(json.dumps(response, ensure_ascii=False), flush=True)
                    finished.wait(args.seconds)
                finally:
                    signal.signal(signal.SIGTERM, previous)
                    response = client.request(path, "POST", {"enabled": False})
        print(json.dumps(response, ensure_ascii=False))
        return 0 if response.get("ok") or (response.get("operation") or {}).get("status") == "pending" else 1
    except (APIError, ValueError, OSError) as exc:
        print(
            json.dumps(
                exc.response if isinstance(exc, APIError) else {"ok": False, "error": str(exc)}, ensure_ascii=False
            )
        )
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
