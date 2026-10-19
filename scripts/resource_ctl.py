#!/usr/bin/env python3
"""Public service/device client; hardware and state remain on the serving Pi."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.api_client import APIClient, APIError


def _route(args):
    if args.kind == "service":
        if not args.name:
            raise ValueError("service_required")
        path = (
            "/api/services/" + quote(args.name, safe="") + "/logs"
            if args.action == "logs"
            else "/svc/" + quote(args.name, safe="")
        )
        method = "GET" if args.action in {"status", "logs"} else "POST"
    elif args.kind == "face":
        path = "/api/face-studio/runtime" + ("" if args.action == "status" else "/" + args.action)
        method = "GET" if args.action == "status" else "POST"
    else:
        path = "/api/resource/" + args.kind
        method = "GET" if args.action == "status" else "POST"
    return path, method


def _client(args):
    if args.direct:
        from common.local_api_client import LocalAPIClient

        return LocalAPIClient(args.url)
    return APIClient(args.url)


def _wait_direct_face(client, result):
    import signal
    from threading import Event

    from services.api_core import face_anim

    finished = Event()
    previous = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, lambda *_: finished.set())
    try:
        print(json.dumps(result, ensure_ascii=False), flush=True)
        while face_anim.get_state()["state"]["playing"] and not finished.wait(0.25):
            pass
    finally:
        signal.signal(signal.SIGTERM, previous)
        result = client.request("/api/face-studio/runtime/stop", "POST", {})
    return result


def _request_resource(args):
    body = json.loads(args.payload)
    if not isinstance(body, dict):
        raise ValueError("payload_object_required")
    client = _client(args)
    path, method = _route(args)
    if method == "POST":
        body["action"] = args.action
    direct_face = args.direct and args.kind == "face" and args.action == "play"
    if direct_face:
        body.setdefault("duration_s", 5)
        if type(body["duration_s"]) not in (int, float) or not 1 <= body["duration_s"] <= 300:
            raise ValueError("direct_face_requires_bounded_duration")
    result = client.request(path, method, None if method == "GET" else body)
    return _wait_direct_face(client, result) if direct_face else result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["service", "lcd", "led", "face", "camera"])
    parser.add_argument("action")
    parser.add_argument("name", nargs="?")
    parser.add_argument("--url")
    parser.add_argument("--direct", action="store_true", help="Local emergency transport; use when API is stopped")
    parser.add_argument("--payload", default="{}")
    args = parser.parse_args(argv)
    try:
        result = _request_resource(args)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") or (result.get("operation") or {}).get("status") == "pending" else 1
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
