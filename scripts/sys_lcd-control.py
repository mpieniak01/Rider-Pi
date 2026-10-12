#!/usr/bin/env python3
"""Public LCD alias; the API uses the sole LCD hardware configuration."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.resource_ctl import main

if __name__ == "__main__":
    raise SystemExit(main(["lcd", *sys.argv[1:]]))
