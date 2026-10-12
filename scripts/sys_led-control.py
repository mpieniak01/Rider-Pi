#!/usr/bin/env python3
"""Public LED client; --direct uses the same handlers without an HTTP server."""

from __future__ import annotations

import argparse
import json
import math
import signal
import sys
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.api_client import APIClient, APIError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["on", "off", "auto", "status", "list", "blink"])
    parser.add_argument("--led")
    parser.add_argument("--url")
    parser.add_argument("--direct", action="store_true")
    parser.add_argument("--hz", type=float, default=2)
    parser.add_argument("--on-ms", type=int)
    parser.add_argument("--off-ms", type=int)
    args = parser.parse_args(argv)
    try:
        if args.direct:
            from common.local_api_client import LocalAPIClient

            client = LocalAPIClient(args.url)
        else:
            client = APIClient(args.url)
        body = {"name": args.led, "action": args.action}
        path = "/api/resource/led"
        if args.action in {"list", "status"}:
            if args.led:
                from urllib.parse import urlencode

                path += "?" + urlencode({"name": args.led})
            result = client.request(path)
        else:
            if args.action == "blink":
                if not math.isfinite(args.hz) or not 0 < args.hz <= 500:
                    raise ValueError("invalid_led_frequency")
                delay = round(500 / args.hz)
                body.update(
                    on_ms=delay if args.on_ms is None else args.on_ms,
                    off_ms=delay if args.off_ms is None else args.off_ms,
                )
            result = client.request(path, "POST", body)
            if args.action == "blink":
                generation = result["data"]["generation"]
                name = result["data"]["name"]
                finished = Event()
                previous = signal.getsignal(signal.SIGTERM)
                signal.signal(signal.SIGTERM, lambda *_: finished.set())
                try:
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                    finished.wait()
                finally:
                    signal.signal(signal.SIGTERM, previous)
                    result = client.request(path, "POST", {"action": "off", "name": name, "if_generation": generation})
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    except (APIError, ValueError, OSError) as error:
        print(json.dumps(error.response if isinstance(error, APIError) else {"ok": False, "error": str(error)}))
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
