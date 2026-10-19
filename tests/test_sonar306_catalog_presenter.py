"""Catalog and presenter regressions use inert modules, never real LCD or services."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from common import service_catalog as catalog
from services import camera_pipeline_store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def presenter():
    path = ROOT / "scripts/dev_face-presenter.py"
    spec = importlib.util.spec_from_file_location("sonar306_presenter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "feature,options,expected",
    [
        ("s5_voice", {"domain": "asr"}, ("rider-voice-web.service",)),
        ("s5_voice", {"domain": "tts"}, ("rider-voice-web.service",)),
        ("s5_voice", {"domain": "voice"}, ("rider-voice-web.service", "rider-voice.service")),
        ("s10_ai_providers", {"domain": "text"}, ("rider-voice-web.service",)),
        ("s10_ai_providers", {"domain": "vision"}, (*catalog.CAMERA_UNITS, "rider-vision-offload.service")),
        ("s11_dev_mode", {"tool": "raw"}, catalog.CAMERA_UNITS),
        ("s11_dev_mode", {"tool": "edge"}, ("camera-capture@edge.service",)),
        ("s11_dev_mode", {"tool": "ssd"}, ("camera-capture@ssd.service",)),
    ],
)
def test_catalog_selects_only_requested_domain_or_tool(monkeypatch, feature, options, expected):
    monkeypatch.setattr(camera_pipeline_store, "enabled", lambda: False)
    definition = catalog.DEFAULT_REGISTRY[feature]
    expected_units = tuple(dict.fromkeys((*catalog.BASE_UNITS, *expected, *definition.services)))
    assert catalog.task_units(definition, options) == expected_units


@pytest.mark.parametrize(
    "feature,options,error",
    [
        ("s5_voice", {"domain": "text"}, "unsupported domain"),
        ("s5_voice", {"domain": "bad", "extra": True}, "unsupported task option"),
        ("s10_ai_providers", {"domain": "bad"}, "unsupported domain"),
        ("s11_dev_mode", {"tool": "jupyter"}, "Jupyter is manual"),
    ],
)
def test_catalog_rejects_invalid_selection_before_observing_pipeline(monkeypatch, feature, options, error):
    enabled = Mock(side_effect=AssertionError("invalid selection reached runtime observation"))
    monkeypatch.setattr(camera_pipeline_store, "enabled", enabled)
    definition = catalog.DEFAULT_REGISTRY[feature]
    with pytest.raises(ValueError, match=error):
        catalog.task_units(definition, options)
    enabled.assert_not_called()


def test_pipeline_retains_capture_without_a_duplicate_distributor(monkeypatch):
    monkeypatch.setattr(camera_pipeline_store, "enabled", lambda: True)
    units = catalog.task_units(catalog.DEFAULT_REGISTRY["s11_dev_mode"], {"tool": "raw"})
    assert "camera-capture@raw.service" in units
    assert "frame-distributor.service" not in units
    assert tuple(dict.fromkeys(units)) == units


def test_presenter_skips_failed_factories_and_broken_modules(presenter, monkeypatch):
    broken = Mock(side_effect=RuntimeError("unavailable"))
    broken.ShowImage = Mock()
    wanted = object()
    factory = Mock(return_value=wanted)
    factory.ShowImage = Mock()
    package = SimpleNamespace(__name__="xgoscreen", __path__=[], a=broken)
    child = SimpleNamespace(device=factory)

    def load(name):
        if name == "xgoscreen":
            return package
        if name == "xgoscreen.broken":
            raise ImportError("optional backend absent")
        return child

    monkeypatch.setattr(presenter.importlib, "import_module", load)
    monkeypatch.setattr(
        presenter.pkgutil,
        "walk_packages",
        lambda *args: [(None, "xgoscreen.broken", False), (None, "xgoscreen.good", False)],
    )
    assert presenter.find_presenter() is wanted
    broken.assert_called_once()
    factory.assert_called_once()


def test_presenter_preserves_successful_none_factory_without_falling_through(presenter, monkeypatch):
    factory = Mock(return_value=None)
    factory.ShowImage = Mock()
    package = SimpleNamespace(device=factory)
    monkeypatch.setattr(presenter.importlib, "import_module", lambda name: package)
    walk = Mock(side_effect=AssertionError("successful factory must not inspect submodules"))
    monkeypatch.setattr(presenter.pkgutil, "walk_packages", walk)
    assert presenter.find_presenter() is None
    walk.assert_not_called()


def test_presenter_does_not_swallow_keyboard_interrupt(presenter):
    factory = Mock(side_effect=KeyboardInterrupt())
    factory.ShowImage = Mock()
    package = SimpleNamespace(device=factory)
    with pytest.raises(KeyboardInterrupt):
        presenter._presenter_in(package)


def test_presenter_initialization_keeps_all_backend_hooks(presenter):
    device = SimpleNamespace(
        begin=Mock(side_effect=OSError("first hook failed")), Init=Mock(), SPI=SimpleNamespace(mode=0)
    )
    presenter._configure_presenter(device, 1000, 2)
    device.begin.assert_called_once()
    device.Init.assert_called_once()
    assert device.SPI.max_speed_hz == 1000
    assert device.SPI.mode == 2


def test_presenter_summary_has_no_spurious_none_line(presenter, monkeypatch, capsys):
    device = SimpleNamespace(width=2, height=3, ShowImage=Mock())
    monkeypatch.setattr(sys, "argv", ["dev_face-presenter.py", "--secs", "0"])
    monkeypatch.setattr(presenter, "find_presenter", lambda: device)
    monkeypatch.setattr(presenter.time, "time", lambda: 100)
    presenter.main()
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 1
    assert output.startswith("fps~0.00 W=2 H=3")
    assert "None" not in output
    device.ShowImage.assert_not_called()


def test_reset_summary_without_importing_or_executing_lcd_code(capsys):
    tree = ast.parse((ROOT / "scripts/dev_panel-reset.py").read_text())
    summary = ast.Module(body=[tree.body[-1]], type_ignores=[])
    namespace = {"SPIHZ": 0, "spi": SimpleNamespace(max_speed_hz=1200, mode=1)}
    exec(compile(summary, "reset-summary", "exec"), namespace)
    assert capsys.readouterr().out == "... SPI=1200 mode=1\n"
