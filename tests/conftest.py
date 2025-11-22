#!/usr/bin/env python3
"""Global test fixtures."""

import pytest


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
