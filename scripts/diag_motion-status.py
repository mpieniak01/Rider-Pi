#!/usr/bin/env python3
"""Read-only observation. No SDK, UART, service start or arming."""

from __future__ import annotations

import argparse
import json
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("api", nargs="?", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    base = args.api if "://" in args.api else "http://" + args.api
    for path in ("/healthz", "/api/version", "/api/control/state", "/api/devices"):
        with urllib.request.urlopen(base.rstrip("/") + path, timeout=3) as response:
            body = json.load(response)
        print(json.dumps({"path": path, "observation": body}, ensure_ascii=False))


if __name__ == "__main__":
    main()
