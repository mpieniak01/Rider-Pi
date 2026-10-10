"""Exact privileged read of the motion UART, including non-cooperating owners.

Uses existing noninteractive sudo permission. Permission/tool/read failures are
unknown; no policy is installed and no process or device is changed.
"""

from __future__ import annotations

import os
import subprocess
import time

UART_PORT = "/dev/ttyAMA0"


def read_uart_owners(port: str = UART_PORT, *, timeout_s: float = 2.0) -> dict:
    observed_at = time.time()
    base = {"known": False, "owners": [], "unreadable": [], "source": "privileged_lsof", "observed_at": observed_at}
    if port != UART_PORT or not os.path.exists(port):
        return {**base, "error": "unsupported_or_missing_motion_uart", "unreadable": [port]}
    prefix = [] if os.geteuid() == 0 else ["/usr/bin/sudo", "-n"]
    try:
        proc = subprocess.run(
            [*prefix, "/usr/bin/lsof", "-Fp", "--", port],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {**base, "error": str(exc), "unreadable": [port]}
    if proc.returncode not in {0, 1} or proc.stderr.strip():
        return {**base, "error": proc.stderr.strip() or "UART owner query failed", "unreadable": [port]}
    try:
        owners = sorted({int(line[1:]) for line in proc.stdout.splitlines() if line.startswith("p")})
    except ValueError:
        return {**base, "error": "malformed_UART_owner_result", "unreadable": [port]}
    if (proc.returncode == 0 and not owners) or (proc.returncode == 1 and proc.stdout.strip()):
        return {**base, "error": "incomplete_UART_owner_result", "unreadable": [port]}
    return {**base, "known": True, "owners": owners, "error": None}
