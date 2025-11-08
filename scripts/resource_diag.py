#!/usr/bin/env python3
"""CLI do diagnostyki i zwalniania zasobów (mikrofon/głośnik/kamera)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable

from services.api_core import resource_diag


def _parse_pids(values: Iterable[str] | None) -> list[int]:
    if not values:
        return []
    out: list[int] = []
    for value in values:
        try:
            out.append(int(value))
        except ValueError:
            raise SystemExit(f"Invalid PID: {value}") from None
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnostyka zasobów sprzętowych")
    parser.add_argument("action", choices=["status", "release"], help="Akcja")
    parser.add_argument("resource", choices=resource_diag.available_resources(), help="Nazwa zasobu")
    parser.add_argument("--pid", dest="pids", action="append", help="Ogranicz działanie do wskazanego PID")
    args = parser.parse_args()

    if args.action == "status":
        data = resource_diag.inspect(args.resource)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    limit_pids = _parse_pids(args.pids)
    data = resource_diag.release(args.resource, limit_pids=limit_pids)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if data.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
