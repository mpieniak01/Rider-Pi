#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from apps.app_logic_core import FeatureManager
from common.service_catalog import DEFAULT_ALIASES, DEFAULT_REGISTRY


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sterowanie funkcjami Rider-Pi przez FeatureManager.")
    parser.add_argument("action", choices=["start", "stop", "status"], help="Akcja na funkcji.")
    parser.add_argument(
        "feature",
        nargs="?",
        help="Nazwa funkcji/scenariusza (np. s3_follow_me_face, face_tracking, s4_recon).",
    )
    parser.add_argument("--control-file", type=Path, help="Fresh operator envelope JSON; moving starts require a TTY.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    control = None
    feature = DEFAULT_REGISTRY.get(DEFAULT_ALIASES.get(args.feature, args.feature))
    if args.action == "start" and feature and feature.can_move:
        if not sys.stdin.isatty() or args.control_file is None:
            print(json.dumps({"ok": False, "error": "moving_start_requires_operator_tty_and_control_file"}))
            return 2
        try:
            if args.control_file.stat().st_size > 65536:
                raise ValueError("control_file_oversized")
            control = json.loads(args.control_file.read_text(encoding="utf-8"))
            if not isinstance(control, dict):
                raise ValueError("control_object_required")
        except (OSError, ValueError):
            print(json.dumps({"ok": False, "error": "invalid_operator_control_file"}))
            return 2
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
        result = manager.set_feature(args.feature, enabled, control=control)
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
