#!/usr/bin/env python3
"""Observe executor telemetry; never open a second UART or instantiate the SDK."""

import runpy
import sys
from pathlib import Path


def main():
    script = Path(__file__).resolve().parents[1] / "scripts" / "diag_motion-status.py"
    sys.argv = [str(script)] + sys.argv[1:]
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
