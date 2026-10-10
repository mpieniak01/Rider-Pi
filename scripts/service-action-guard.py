#!/usr/bin/env python3
"""Fail-closed entry point; checks live in common.service_action_guard."""

from __future__ import annotations

import json
import sys

from common.service_action_guard import check

if __name__ == "__main__":
    try:
        result = check(*sys.argv[1:]) if len(sys.argv) == 3 else {"ok": False, "error": "unit_and_action_required"}
    except (ImportError, OSError, ValueError) as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result))
    sys.exit(0 if result.get("ok") else 3)
