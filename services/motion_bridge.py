"""Retired direct-UART bridge. The supported executor owns every actuator.

Compatibility topics ("cmd.balance", "cmd.height", cmd.move and STOP) are
handled by apps.motion.executor with the canonical consent envelope. Importing
this module creates neither an SDK, socket, timer nor another serial owner.
"""

from __future__ import annotations

import sys


def ensure_xgo_open():
    return None


def main() -> int:
    print(
        "[bridge] direct UART bridge retired; use motion-executor.service and "
        "the operator consent API. No commands were executed.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
