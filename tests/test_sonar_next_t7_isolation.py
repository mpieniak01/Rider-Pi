"""Failure and restoration boundaries for simulator test resources."""

import os
import unittest

import pygame
import pytest
from simulator_fixtures import headless_pygame_session, simulated_robot_session


@pytest.mark.parametrize("initial", [None, "external-sentinel", "dummy"])
@pytest.mark.parametrize("fail_inside", [False, True])
def test_headless_session_cleans_resources_and_restores_environment(monkeypatch, initial, fail_inside):
    if initial is None:
        monkeypatch.delenv("SDL_VIDEODRIVER", raising=False)
    else:
        monkeypatch.setenv("SDL_VIDEODRIVER", initial)
    monkeypatch.setenv("SDL_AUDIODRIVER", "external-audio")
    failure = None
    try:
        with headless_pygame_session(monkeypatch):
            from sim.world import World

            World()
            assert pygame.get_init()
            assert pygame.display.get_init()
            assert pygame.display.get_surface() is not None
            if fail_inside:
                raise RuntimeError("fixture body failed")
    except RuntimeError as error:
        failure = str(error)
    expected_failure = "fixture body failed" if fail_inside else None
    assert failure == expected_failure
    assert not pygame.get_init()
    assert not pygame.display.get_init()
    assert pygame.display.get_surface() is None
    assert os.environ.get("SDL_VIDEODRIVER") == initial
    assert os.environ["SDL_AUDIODRIVER"] == "external-audio"


@pytest.mark.parametrize("initial", [None, "0", "1", "external-sentinel"])
def test_simulation_toggle_cleans_environment_and_preserves_exports(monkeypatch, initial):
    from test_simulation_toggle import TestSimulationToggle

    import drivers.lcd
    import drivers.xgo

    if initial is None:
        monkeypatch.delenv("RIDER_SIMULATOR", raising=False)
    else:
        monkeypatch.setenv("RIDER_SIMULATOR", initial)
    robot_factory = drivers.xgo.get_robot_driver
    lcd_factory = drivers.lcd.get_lcd_driver
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestSimulationToggle)
    result = unittest.TestResult()
    suite.run(result)
    assert result.testsRun == 6
    assert result.wasSuccessful(), (result.errors, result.failures)
    assert os.environ.get("RIDER_SIMULATOR") == initial
    assert drivers.xgo.get_robot_driver is robot_factory
    assert drivers.lcd.get_lcd_driver is lcd_factory


@pytest.mark.parametrize("fail_inside", [False, True])
def test_virtual_robot_scope_closes_subscription_on_success_or_error(fail_inside):
    failure = None
    try:
        with simulated_robot_session(x=5.0) as robot:
            subscriber = robot._sub
            assert subscriber is not None
            assert not subscriber.closed
            if fail_inside:
                raise RuntimeError("virtual robot body failed")
    except RuntimeError as error:
        failure = str(error)
    expected_failure = "virtual robot body failed" if fail_inside else None
    assert failure == expected_failure
    assert subscriber.closed
