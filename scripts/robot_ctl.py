#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from apps.app_logic_core import FeatureManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sterowanie funkcjami Rider-Pi przez FeatureManager.")
    parser.add_argument("action", choices=["start", "stop", "status"], help="Akcja na funkcji.")
    parser.add_argument(
        "feature",
        nargs="?",
        help="Nazwa funkcji/scenariusza (np. s3_follow_me_face, face_tracking, s4_recon).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manager = FeatureManager()
    if args.action == "status":
        state = manager.state_snapshot()
        print(json.dumps({"ok": True, "state": state}, ensure_ascii=False, indent=2))
        return 0

    if not args.feature:
        print(json.dumps({"ok": False, "error": "feature_required"}))
        return 2

    enabled = args.action == "start"

    try:
        result = manager.set_feature(args.feature, enabled)
        ok = bool(result.get("ok", False))
        payload: dict[str, Any] = {
            "ok": ok,
            "feature": args.feature,
            "enabled": enabled,
            "result": result,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    except ValueError:
        print(json.dumps({"ok": False, "error": f"unknown_feature:{args.feature}"}))
        return 1
    except Exception as e:  # pragma: no cover - awarie środowiska/systemd
        print(json.dumps({"ok": False, "error": f"feature_error:{e}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
