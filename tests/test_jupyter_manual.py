"""Jupyter stays installed for manual use and has no automatic start sources."""

from __future__ import annotations

import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_vendor_cleanup_stops_jupyter_without_restarting_it():
    # Inspect the exact recipe: executing make could reach a real systemctl.
    lines = (ROOT / "Makefile").read_text().splitlines()
    start = lines.index("vendor-kill:") + 1
    recipe = []
    for line in lines[start:]:
        if not line.startswith("\t"):
            break
        recipe.append(shlex.split(line.lstrip("\t@")))
    commands = [tokens[tokens.index("systemctl") + 1 :] for tokens in recipe if "systemctl" in tokens]
    assert any(command[:2] == ["stop", "jupyter.service"] for command in commands)
    assert all(command[0] == "stop" for command in commands)


def test_jupyter_has_no_automatic_target_membership():
    assert "WantedBy=" not in (ROOT / "systemd/jupyter.service").read_text()
    assert "jupyter.service" not in (ROOT / "systemd/rider-dev.target").read_text()
