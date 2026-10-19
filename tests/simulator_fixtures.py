"""Headless simulator lifetime shared by software-only world tests."""

from contextlib import ExitStack, contextmanager

import pygame
import pytest


@contextmanager
def headless_pygame_session(monkeypatch):
    with monkeypatch.context() as temporary:
        temporary.setenv("SDL_VIDEODRIVER", "dummy")
        temporary.setenv("SDL_AUDIODRIVER", "dummy")
        try:
            yield
        finally:
            pygame.quit()


@pytest.fixture
def headless_pygame(monkeypatch):
    with headless_pygame_session(monkeypatch):
        yield


@contextmanager
def simulated_robot_session(**kwargs):
    from sim.robot import SimulatedRobot

    robot = SimulatedRobot(**kwargs)
    try:
        yield robot
    finally:
        if robot._sub is not None:
            robot._sub.close(linger=0)


@pytest.fixture
def robot_factory():
    with ExitStack() as resources:

        def create(**kwargs):
            return resources.enter_context(simulated_robot_session(**kwargs))

        yield create
