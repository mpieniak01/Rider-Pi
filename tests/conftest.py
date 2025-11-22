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
        import zmq

        zmq.Context.instance().term()
    except Exception:
        pass
