#!/usr/bin/env python3
"""Internal privileged LED writer; called by the API, not a second manager."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drivers.led import apply

if __name__ == "__main__":
    try:
        payload = json.loads(sys.argv[1])
        if not isinstance(payload, dict):
            raise ValueError("JSON_object_required")
        print(json.dumps(apply(payload)))
    except (ValueError, OSError, IndexError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1) from error
