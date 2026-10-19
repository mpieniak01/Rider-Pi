"""LCD backend behavior with injected GPIO/SPI implementations; never real hardware."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def backend(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "lcd_gate_backend", Path(__file__).resolve().parents[1] / "scripts/lcd-power-backend.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    gpio = SimpleNamespace(
        BCM=11, OUT=1, LOW=0, HIGH=1, setwarnings=Mock(), setmode=Mock(), setup=Mock(), output=Mock()
    )
    spi = SimpleNamespace(open=Mock(), close=Mock(), writebytes=Mock())
    monkeypatch.setitem(sys.modules, "RPi", SimpleNamespace(GPIO=gpio))
    monkeypatch.setitem(sys.modules, "RPi.GPIO", gpio)
    monkeypatch.setitem(sys.modules, "spidev", SimpleNamespace(SpiDev=lambda: spi))
    monkeypatch.setattr(module, "time", SimpleNamespace(sleep=lambda seconds: None))
    return module, gpio, spi


def test_power_sequence_and_status_do_not_confuse_observation_with_mutation(backend, capsys):
    module, gpio, spi = backend
    args = SimpleNamespace(no_spi=False, dc=4, rst=5, spi="/dev/spidev0.0", hz=1000000, bl=6, bl_ah=1)
    assert module.do_on(args) == 0
    assert [call.args[0] for call in spi.writebytes.call_args_list] == [[0x11], [0x29]]
    spi.writebytes.reset_mock()
    gpio.output.reset_mock()
    assert module.do_off(args) == 0
    assert [call.args[0] for call in spi.writebytes.call_args_list] == [[0x28], [0x10]]
    assert gpio.output.call_args.args == (6, 0)
    spi.writebytes.reset_mock()
    gpio.output.reset_mock()
    assert module.do_status(args) == 0
    spi.writebytes.assert_not_called()
    gpio.output.assert_not_called()


def test_hardware_failure_is_reported_and_spi_is_closed(backend):
    module, gpio, spi = backend
    spi.writebytes.side_effect = OSError("injected failure")
    assert module._spi_cmds(4, 5, "/dev/spidev0.0", 1000000, [0x11]) is False
    spi.close.assert_called_once()
    gpio.output.side_effect = OSError("injected failure")
    assert module._set_bl(6, 1, True) is False
    assert module._set_bl(-1, 1, True) is True
    assert module._spi_cmds(4, 5, "none", 1000, [0x11]) is True


@pytest.mark.parametrize("result,expected", [(0, 0), (2, 1)])
def test_cli_returns_failure_when_action_is_unconfirmed(backend, monkeypatch, result, expected):
    module, gpio, spi = backend
    monkeypatch.setattr(module, "_parse", lambda: SimpleNamespace(func=lambda args: result))
    monkeypatch.setattr(module, "_has_root", lambda: False)
    assert module.main() == expected


def test_cli_parser_keeps_explicit_no_spi_scope(backend, monkeypatch):
    module, gpio, spi = backend
    monkeypatch.setattr(sys, "argv", ["lcd-power", "on", "--no-spi"])
    args = module._parse()
    assert args.no_spi is True
    assert args.func == module.do_on
