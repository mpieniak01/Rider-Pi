"""Reports must fail on broken contracts while remaining import-safe and isolated."""

from __future__ import annotations

import importlib.util
import os
import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_test_module(filename):
    """Load a checker without invoking its command-line entry point."""
    spec = importlib.util.spec_from_file_location("isolated_" + filename[:-3], ROOT / "tests" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def report_modules(monkeypatch):
    """Use simulator-shaped fakes so no window, publisher or hardware is opened."""
    monkeypatch.syspath_prepend(str(ROOT / "tests"))
    worlds = []
    overrides = {}

    def create_world(**_kwargs):
        world = SimpleNamespace(
            screen=object(),
            width=1280,
            height=720,
            main_panel_width=896,
            side_panel_width=384,
            map_width=15,
            map_height=10,
            walls=[(0, 0)],
            start_pos=(1, 1),
            goal=(2, 2),
            wall_segments=[],
            render=Mock(),
            handle_events=Mock(return_value=True),
            quit=Mock(),
        )
        world.__dict__.update(overrides)
        worlds.append(world)
        return world

    class Robot:
        """Only the acceptance reporter's observed robot attributes are simulated."""

        def __init__(self, **position):
            self.__dict__.update(position)
            self.linear_vel = 0.0

        def _handle_command(self, command):
            self.linear_vel = command["lx"]

        def update(self, elapsed):
            self.x += self.linear_vel * elapsed

        def get_state(self):
            return {"x": self.x, "y": self.y, "angle": self.angle}

    def camera(**kwargs):
        surface = SimpleNamespace(
            get_width=lambda: kwargs.get("width", 320), get_height=lambda: kwargs.get("height", 240)
        )
        return SimpleNamespace(_pub=object(), render=Mock(return_value=surface))

    world_module = ModuleType("sim.world")
    world_module.World = Mock(side_effect=create_world)
    robot_module = ModuleType("sim.robot")
    robot_module.SimulatedRobot = Robot
    sensor_module = ModuleType("sim.sensors")
    sensor_module.VirtualCamera = camera
    sensor_module.VirtualGyro = Mock(return_value=SimpleNamespace(_pub=object()))
    for module in [world_module, robot_module, sensor_module]:
        monkeypatch.setitem(sys.modules, module.__name__, module)
    return SimpleNamespace(world=world_module, worlds=worlds, overrides=overrides)


@pytest.mark.parametrize("filename", ["acceptance_criteria.py", "verify_sim1_acceptance.py"])
def test_import_does_not_run_checks_or_open_display(report_modules, filename, capsys):
    """Importing either report must not execute optional simulator dependencies."""
    load_test_module(filename)
    report_modules.world.World.assert_not_called()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("filename,total", [("acceptance_criteria.py", 6), ("verify_sim1_acceptance.py", 4)])
def test_report_returns_success_only_when_all_original_checks_pass(report_modules, filename, total, capsys):
    """Every original acceptance criterion remains part of the report."""
    module = load_test_module(filename)
    assert module.main() == 0
    text = capsys.readouterr().out
    assert f"SUMMARY: {total}/{total} passed, 0/{total} failed" in text
    for world in report_modules.worlds:
        world.quit.assert_called_once()


@pytest.mark.parametrize(
    "filename,broken,total", [("acceptance_criteria.py", "map_width", 6), ("verify_sim1_acceptance.py", "screen", 4)]
)
def test_assertion_failure_is_reported_and_later_checks_continue(report_modules, filename, broken, total, capsys):
    """One broken contract yields failure without suppressing the later criteria."""
    report_modules.overrides[broken] = 0 if broken == "map_width" else None
    module = load_test_module(filename)
    assert module.main() == 1
    text = capsys.readouterr().out
    assert "[AC1] ✗ Failed:" in text
    assert f"[{ 'AC6' if total == 6 else 'AC4' }] ✓" in text
    assert f"SUMMARY: {total - 1}/{total} passed, 1/{total} failed" in text
    for world in report_modules.worlds:
        world.quit.assert_called_once()


@pytest.mark.parametrize("filename", ["acceptance_criteria.py", "verify_sim1_acceptance.py"])
@pytest.mark.parametrize("broken", [False, True])
def test_cli_exit_code_matches_the_report(report_modules, filename, broken):
    """The actual __main__ path returns a nonzero process status on failure."""
    if broken:
        report_modules.overrides.update(map_width=0, screen=None)
    path = str(ROOT / "tests" / filename)
    with pytest.raises(SystemExit) as exit_status:
        runpy.run_path(path, run_name="__main__")
    assert exit_status.value.code == (1 if broken else 0)


@pytest.mark.parametrize("previous", [None, "operator-display"])
def test_failed_world_check_closes_display_and_restores_environment(report_modules, monkeypatch, previous):
    """Failure still closes the simulator and restores the caller's display setting."""
    import acceptance_report

    if previous is None:
        monkeypatch.delenv("SDL_VIDEODRIVER", raising=False)
    else:
        monkeypatch.setenv("SDL_VIDEODRIVER", previous)
    failure = ValueError("broken check")
    context = acceptance_report.simulation_world()
    with pytest.raises(ValueError, match="broken check"):
        with context:
            raise failure
    report_modules.worlds[0].quit.assert_called_once()
    assert os.environ.get("SDL_VIDEODRIVER") == previous


def test_world_constructor_failure_restores_environment(report_modules, monkeypatch):
    """A failing optional backend must not leak process-wide display configuration."""
    import acceptance_report

    monkeypatch.setenv("SDL_VIDEODRIVER", "operator-display")
    report_modules.world.World.side_effect = RuntimeError("display backend failed")
    context = acceptance_report.simulation_world()
    with pytest.raises(RuntimeError, match="display backend failed"):
        with context:
            pass
    assert os.environ["SDL_VIDEODRIVER"] == "operator-display"


def test_empty_criteria_are_configuration_failure(report_modules, capsys):
    """Zero exercised criteria must never produce a successful report."""
    import acceptance_report

    assert acceptance_report.run_criteria("empty", []) == 2
    assert "no acceptance criteria" in capsys.readouterr().out


@pytest.mark.parametrize("error", [RuntimeError("backend failed"), AssertionError()])
def test_report_records_runtime_and_empty_assertion_errors(report_modules, error, capsys):
    """Both backend errors and assertions produce visible failure and continue."""
    import acceptance_report

    bad = Mock(side_effect=error)
    later = Mock(return_value="✓ later check")
    assert acceptance_report.run_criteria("report", [("AC1", "broken", bad), ("AC2", "later", later)]) == 1
    later.assert_called_once()
    message = str(error) or type(error).__name__
    assert message in capsys.readouterr().out


def test_report_does_not_consume_operator_interrupt(report_modules):
    """Cancellation is propagated instead of being turned into a failed criterion."""
    import acceptance_report

    bad = Mock(side_effect=KeyboardInterrupt)
    later = Mock()
    criteria = [("AC1", "interrupt", bad), ("AC2", "later", later)]
    with pytest.raises(KeyboardInterrupt):
        acceptance_report.run_criteria("report", criteria)
    later.assert_not_called()


@pytest.mark.parametrize("regression", ["missing_main", "constructor", "missing_method"])
def test_tracking_contract_regressions_fail_instead_of_skipping(monkeypatch, regression):
    """A broken controller import contract cannot be hidden as an optional SDK skip."""
    from apps.motion import tracking_controller

    checker = load_test_module("test_vision_tracking.py")
    if regression == "missing_main":
        monkeypatch.setattr(tracking_controller, "main", None)
    elif regression == "constructor":
        monkeypatch.setattr(tracking_controller, "TrackingController", Mock(side_effect=RuntimeError("regression")))
    else:
        monkeypatch.setattr(tracking_controller, "TrackingController", Mock(return_value=SimpleNamespace()))
    error = RuntimeError if regression == "constructor" else AssertionError
    with pytest.raises(error):
        checker.test_tracking_controller_imports()


def test_lcd_import_errors_are_not_accepted_based_on_message(monkeypatch):
    """A backend error mentioning PIL must fail rather than satisfy a string check."""
    import builtins

    checker = load_test_module("test_graceful_shutdown.py")
    original = builtins.__import__

    def broken_import(name, *args, **kwargs):
        if name == "drivers.lcd.driver_ili9xx":
            raise RuntimeError("PIL regression")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken_import)
    with pytest.raises(RuntimeError, match="PIL regression"):
        checker.test_lcd_renderer_cleanup()
