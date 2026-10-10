"""Jupyter stays installed for manual use and has no automatic start sources."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_vendor_cleanup_stops_jupyter_without_restarting_it(tmp_path):
    calls = tmp_path / "calls"
    systemctl = tmp_path / "systemctl"
    systemctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n')
    systemctl.chmod(0o755)
    env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ["PATH"], CALLS=str(calls))
    subprocess.run(["make", "vendor-kill", "SUDO="], cwd=ROOT, env=env, check=True, capture_output=True, timeout=5)
    commands = calls.read_text().splitlines()
    assert "stop jupyter.service" in commands
    assert not any(command.startswith(("start ", "restart ")) for command in commands)


def test_jupyter_has_no_automatic_target_membership():
    assert "WantedBy=" not in (ROOT / "systemd/jupyter.service").read_text()
    assert "jupyter.service" not in (ROOT / "systemd/rider-dev.target").read_text()
