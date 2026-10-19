"""Static camera stop regression; no subprocess, systemd or hardware imports."""

from __future__ import annotations

import ast
import configparser
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_capture_stop_targets_flock_and_its_child_with_sigterm():
    unit = configparser.ConfigParser(interpolation=None, strict=False)
    unit.read(ROOT / "systemd/camera-capture@.service")
    service = unit["Service"]
    # KillMode=process only ended the flock MainPID, leaving capture and its
    # V4L2/lock descriptors alive despite systemd reporting inactive.
    assert service["KillMode"] == "control-group"
    assert service["KillSignal"] == "SIGTERM"
    assert service["TimeoutStopSec"] == "5"
    assert service["Type"] == "simple"
    assert shlex.split(service["ExecStart"]) == [
        "/usr/bin/flock",
        "-n",
        "/tmp/camera.lock",
        "/usr/bin/python3",
        "-u",
        "-m",
        "apps.camera.capture_service",
    ]
    assert "ExecStop" not in service
    assert "ExecStopPost" not in service


@pytest.mark.parametrize(
    ("mode", "module"),
    [
        ("raw", "apps.camera.preview_lcd"),
        ("edge", "apps.vision.edge_preview"),
        ("ssd", "apps.camera.preview_lcd_ssd"),
    ],
)
def test_template_modes_share_supervised_entrypoint_and_do_not_ignore_sigterm(mode, module):
    entrypoint = ast.parse((ROOT / "apps/camera/capture_service.py").read_text())
    mapping = next(
        node.value for node in entrypoint.body if isinstance(node, ast.AnnAssign) and node.target.id == "MODE_MAP"
    )
    modules = {key.value: value.args[0].value for key, value in zip(mapping.keys, mapping.values)}
    assert modules[mode] == module
    producer = ast.parse((ROOT / (module.replace(".", "/") + ".py")).read_text())
    for node in ast.walk(producer):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "signal" or len(node.args) < 2:
            continue
        if isinstance(node.args[0], ast.Attribute) and node.args[0].attr == "SIGTERM":
            assert not (isinstance(node.args[1], ast.Attribute) and node.args[1].attr == "SIG_IGN")
