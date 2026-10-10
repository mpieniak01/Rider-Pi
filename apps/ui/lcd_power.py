"""Exact LCD-only off command, guarded by current descriptor ownership.

No SDK/UART imports and no generic resource release, process signal or service
action. A successful control write is not a physical power measurement.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from apps.ui.status_panel import ownership_permits


def off_if_free(*, probe=None, runner=None):
    if probe is None:
        from services.api_core.resource_diag import inspect

        def probe():
            return inspect("lcd")

    if runner is None:
        runner = subprocess.run
    snapshot = probe()
    # This helper itself owns no descriptors. Any owner blocks its OFF command.
    if not ownership_permits(snapshot) or snapshot.get("free") is not True:
        return {"ok": False, "on": None, "power_known": False, "error": "lcd_owned_or_unknown"}
    controller = Path(__file__).resolve().parents[2] / "scripts" / "sys_lcd-control.py"
    # Match the existing renderer's backlight configuration, never change pins.
    # Installed xgoscreen LCD_2inch backend uses BCM0. Generic ST7789/face
    # backends have different defaults and must not override the XGO board.
    pin = os.getenv("FACE_LCD_BL_PIN", "0")
    prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
    try:
        result = runner(
            [*prefix, sys.executable, str(controller), "off", "--bl", pin, "--rst", "-1"],
            timeout=3,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "on": None, "power_known": False, "error": "lcd_off_unconfirmed:" + type(exc).__name__}
    accepted = result.returncode == 0
    return {
        "ok": accepted,
        "on": False if accepted else None,
        "power_known": accepted,
        "error": None if accepted else "lcd_off_unconfirmed",
        "confirmation": "control_write_accepted",
        "physical_validity": "unverified",
    }
