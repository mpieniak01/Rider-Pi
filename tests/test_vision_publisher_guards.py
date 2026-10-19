"""Publishing guards use fake sockets and never start vision or robot services."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ["dispatcher", "tracker_mediapipe"]


@pytest.fixture(params=MODULES)
def publisher_module(request, monkeypatch):
    """Load a private module instance, isolated from tests patching dispatcher.pub."""
    monkeypatch.setitem(sys.modules, "mediapipe", ModuleType("mediapipe"))
    name = "_vision_publish_" + request.param
    spec = importlib.util.spec_from_file_location(name, ROOT / "apps" / "vision" / (request.param + ".py"))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def test_absent_publisher_is_reported_before_serialization(publisher_module, monkeypatch, capsys):
    """Unavailable publishing is a diagnosed no-op rather than a swallowed assertion."""
    serializer = Mock()
    monkeypatch.setattr(publisher_module.json, "dumps", serializer)
    result = publisher_module.pub("vision.state", {"unserializable": object()})
    assert result is None
    serializer.assert_not_called()
    assert "pub err: publisher not initialized" in capsys.readouterr().out


def test_publisher_preserves_unicode_wire_format(publisher_module):
    """Initialized publishing retains the topic, JSON and non-ASCII payload contract."""
    publisher_module.PUB = Mock()
    payload = {"label": "zażółć", "present": False, "score": 0.0}
    publisher_module.pub("vision.state", payload)
    publisher_module.PUB.send_string.assert_called_once_with("vision.state " + json.dumps(payload, ensure_ascii=False))


def test_socket_failure_is_reported_and_later_publish_can_recover(publisher_module, capsys):
    """A transient send failure stays non-throwing and does not discard the publisher."""
    socket = Mock()
    socket.send_string.side_effect = [RuntimeError("socket unavailable"), None]
    publisher_module.PUB = socket
    publisher_module.pub("vision.state", {"present": True})
    assert "pub err: socket unavailable" in capsys.readouterr().out
    assert publisher_module.PUB is socket
    publisher_module.pub("vision.state", {"present": False})
    assert socket.send_string.call_count == 2
    assert "pub err:" not in capsys.readouterr().out


def test_serialization_failure_never_sends_a_partial_message(publisher_module, capsys):
    """Invalid JSON is diagnosed without attempting a socket send."""
    publisher_module.PUB = Mock()
    publisher_module.pub("vision.state", {"invalid": object()})
    publisher_module.PUB.send_string.assert_not_called()
    assert "pub err:" in capsys.readouterr().out


@pytest.mark.parametrize("module_name", MODULES)
@pytest.mark.parametrize("optimization", ["-O", "-OO"])
def test_optimized_python_keeps_the_uninitialized_publisher_guard(module_name, optimization):
    """An actual optimized interpreter retains the diagnostic when assertions vanish."""
    probe = """
import importlib
import sys
from types import ModuleType
from common.test_sandbox import install
install()
sys.modules["mediapipe"] = ModuleType("mediapipe")
module = importlib.import_module("apps.vision." + sys.argv[1])
module.pub("vision.state", {"present": False})
"""
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    result = subprocess.run(
        [sys.executable, optimization, "-c", probe, module_name],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    assert "pub err: publisher not initialized" in result.stdout
