#!/usr/bin/env python3
"""Global test fixtures."""

import os

import pytest

from common.test_sandbox import install

# Collection imports happen before fixtures: isolation must already be enforced.
install()
os.environ["RIDER_CALIBRATION_DIR"] = os.path.join(install.sandbox.name, "calibration")
os.environ["ODOMETRY_STATE_DIR"] = os.path.join(install.sandbox.name, "odometry")
os.environ["ODOMETRY_CALIBRATION_PATH"] = os.path.join(install.sandbox.name, "legacy-calibration.json")


def pytest_collection_modifyitems(items):
    for item in items:
        if item.get_closest_marker("hardware") or item.get_closest_marker("physical_motion"):
            item.add_marker(pytest.mark.skip(reason="Hardware is outside automatic pytest; operator procedure only"))


@pytest.fixture(scope="session", autouse=True)
def _force_face_file_sink():
    """Ustaw FACE_SINK na 'file', aby testy zawsze zapisywały OUT_LATEST."""
    import os

    prev = os.environ.get("FACE_SINK")
    os.environ["FACE_SINK"] = "file"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("FACE_SINK", None)
        else:
            os.environ["FACE_SINK"] = prev


@pytest.fixture(scope="session", autouse=True)
def _silence_voice_ai_mode_monitor():
    """
    Wycisza logi voice.service i blokuje start monitora AI mode,
    aby uniknąć szumów z ContextTerminated po teardown ZMQ.
    """
    import logging

    try:
        import apps.voice.svc_file as svc_file

        svc_file.SpeechService._start_ai_mode_monitor = lambda self: None  # type: ignore[assignment]
    except Exception:
        pass

    logger = logging.getLogger("voice.service")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    logger.setLevel(logging.ERROR)
    yield


@pytest.fixture(scope="session", autouse=True)
def _term_zmq_context():
    """
    Ensure ZMQ global context is terminated after tests to avoid
    `pfd.revents & POLLIN` asserts on interpreter shutdown.
    """
    yield
    try:
        # zatrzymaj ewentualny watchdog providera, aby nie trzymał Contextu
        from services import provider_watchdog

        provider_watchdog.stop()
    except Exception:
        pass
    try:
        import threading

        import zmq

        ctx = zmq.Context.instance()

        def _term():
            try:
                ctx.term()
            except Exception:
                pass

        t = threading.Thread(target=_term, name="zmq-term", daemon=True)
        t.start()
        t.join(timeout=1.0)
    except Exception:
        pass
