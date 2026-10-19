"""Automatic test boundaries, including child interpreters and raw devices."""

from __future__ import annotations

import importlib
import os
import socket
import subprocess
import sys

import pytest

from common.test_sandbox import IsolationError


@pytest.mark.parametrize("module", ["xgolib", "xgoedu", "spidev", "RPi.GPIO"])
def test_real_sdk_import_is_forbidden(module):
    with pytest.raises(IsolationError):
        importlib.import_module(module)


def test_serial_device_open_is_forbidden():
    with pytest.raises(IsolationError):
        os.open("/dev/ttyAMA0", os.O_RDWR)


@pytest.mark.parametrize("address", [("192.0.2.14", 8080), ("127.0.0.1", 5555)])
def test_production_network_and_bus_ports_are_forbidden(address):
    with socket.socket() as client, pytest.raises(IsolationError):
        client.connect(address)


@pytest.mark.parametrize(
    "argv",
    [
        ["ssh", "pi@robot"],
        ["bash", "-lc", "systemctl start motion-executor.service"],
        ["systemctl", "start", "status.service"],
        ["env", "python3", "-S"],
        ["node", "-e", "fetch('http://robot')"],
    ],
)
def test_unapproved_subprocess_cannot_bypass_isolation(argv):
    with pytest.raises(IsolationError):
        subprocess.run(argv, check=False)


def test_child_python_is_bootstrapped_before_user_code():
    result = subprocess.run(
        [sys.executable, "-c", "import socket; socket.socket().connect(('192.0.2.14', 8080))"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "IsolationError" in result.stderr


def test_child_python_cannot_disable_bootstrap():
    with pytest.raises(IsolationError):
        subprocess.run([sys.executable, "-S", "-c", "print('no guards')"], check=False)


def test_system_shell_is_forbidden():
    with pytest.raises(IsolationError):
        os.system("true")


def test_gpio_and_flags_are_detached_from_device():
    assert os.environ["ESTOP_GPIO"] == "-1"
    assert "rider-pytest-" in os.environ["MOTION_FLAGS_DIR"]


@pytest.mark.parametrize("verb", ["add", "commit", "reset", "clean", "branch", "config"])
def test_git_cannot_mutate_checkout(verb):
    cwd = os.getcwd()
    with pytest.raises(IsolationError):
        subprocess.run(["git", verb], cwd=cwd, check=False)


def test_isolated_server_can_bind_ephemeral_loopback():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        assert server.getsockname()[1] >= 32768
