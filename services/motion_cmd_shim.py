#!/usr/bin/env python3
"""Retired routing shim: the executor consumes original legacy frames itself.

Republishing motion.cmd would duplicate commands and used to erase permission
metadata, refresh timestamps and reverse yaw. No broker, UART or SDK is opened.
"""

from common.motion_commands import canonical_command


def translate(payload):
    """Pure compatibility entry for callers; original envelope is unchanged."""
    return canonical_command("motion.cmd", payload)


def main():
    print("[shim] retired: motion.cmd is validated directly by motion-executor", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
