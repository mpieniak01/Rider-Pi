"""This directory runs without hardware, network or parent fixture side effects."""

from __future__ import annotations

import socket
import subprocess
import sys
from types import ModuleType

import pytest


def _deny_bus(*args, **kwargs):
    raise AssertionError("production BUS is forbidden in orchestration tests")


# The fixture is scoped; it cannot replace transport used by other test modules.
_bus = ModuleType("common.bus")
_bus.TOPIC_TRACKING_MODE_SET = "tracking.mode:set"
_bus.TOPIC_NAVIGATOR_RETURN_HOME_START = "navigator.return_home.start"
_bus.BusPub = _deny_bus


@pytest.fixture(autouse=True)
def deny_external_io(monkeypatch, tmp_path):
    def denied(*args, **kwargs):
        raise AssertionError("orchestration tests must inject all external I/O")

    monkeypatch.setattr(subprocess, "run", denied)
    monkeypatch.setattr(subprocess, "check_output", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    import common

    monkeypatch.setitem(sys.modules, "common.bus", _bus)
    monkeypatch.setattr(common, "bus", _bus, raising=False)
    from services.api_core import features_api
    from services.core import lcd_state

    monkeypatch.setattr(
        lcd_state, "backlight_status", lambda: {"on": None, "power_known": False, "error": "mock_unavailable"}
    )

    monkeypatch.setattr(features_api.feature_manager, "_state_path", tmp_path / "api-state.json")
