#!/usr/bin/env python3
"""Operator-only launch of the vendor application with an optional UART observer.

Executing vendor code can reset posture and actuate the robot.
Never run this launcher in automatic tests or services.
"""

import argparse
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drivers.xgo.sniffer import install


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-session", action="store_true", required=True)
    parser.add_argument("application", type=Path)
    args = parser.parse_args()
    application = args.application.resolve(strict=True)
    import serial

    original = serial.Serial
    taps = []

    def observed_serial(*positional, **kwargs):
        owned = original(*positional, **kwargs)
        port = kwargs.get("port", positional[0] if positional else getattr(owned, "port", None))
        if port != "/dev/ttyAMA0":
            return owned
        tapped = install(owned)
        if tapped is not owned:
            taps.append(tapped)
        return tapped

    serial.Serial = observed_serial
    sys.path.insert(0, str(application.parent))
    sys.argv = [str(application)]
    try:
        runpy.run_path(str(application), run_name="__main__")
    finally:
        serial.Serial = original
        for tapped in taps:
            tapped._capture.close()


if __name__ == "__main__":
    main()
