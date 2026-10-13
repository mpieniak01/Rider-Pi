"""Executor process wiring with fake BUS and factory, never hardware."""

from types import SimpleNamespace

import pytest

from apps.motion import executor_runtime
from common import bus


def test_runtime_closes_fake_executor_and_bus_after_signal(monkeypatch):
    calls = []
    handlers = {}
    monkeypatch.setattr(executor_runtime.signal, "signal", lambda sig, fn: handlers.setdefault(sig, fn))
    clock = iter([0, 0.02])
    monkeypatch.setattr(executor_runtime.time, "monotonic", lambda: next(clock))

    class Sub:
        def __init__(self, topics):
            calls.append(("topics", topics))

        def recv(self, timeout_ms):
            if timeout_ms:
                handlers[executor_runtime.signal.SIGTERM](None, None)
                return "motion.command", {"action": "stop"}
            return None, None

        def close(self):
            calls.append("sub_closed")

    class Pub:
        def close(self):
            calls.append("pub_closed")

    def factory(publisher):
        return SimpleNamespace(
            gate=SimpleNamespace(disarm=lambda reason: calls.append(reason)),
            controller=SimpleNamespace(stop=lambda: calls.append("stopped")),
            process_batch=lambda messages: calls.append(("batch", messages)),
            tick=lambda dt: calls.append(("tick", dt)),
            poll_sensors=lambda: calls.append("fake_read"),
            close=lambda: calls.append("executor_closed"),
        )

    monkeypatch.setattr(bus, "BusSub", Sub)
    monkeypatch.setattr(bus, "BusPub", Pub)
    assert executor_runtime.run(factory, ["motion.command"], {"motion.command"}) == 0
    assert "process_signal" in calls and "stopped" in calls
    assert ("tick", 0.02) in calls
    assert calls[-3:] == ["executor_closed", "sub_closed", "pub_closed"]


def test_runtime_closes_bus_when_factory_fails(monkeypatch):
    calls = []
    monkeypatch.setattr(executor_runtime.signal, "signal", lambda *_: None)
    monkeypatch.setattr(bus, "BusSub", lambda _: SimpleNamespace(close=lambda: calls.append("sub")))
    monkeypatch.setattr(bus, "BusPub", lambda: SimpleNamespace(close=lambda: calls.append("pub")))

    def fail(**_):
        raise ValueError("fake initialization failure")

    with pytest.raises(ValueError, match="fake initialization"):
        executor_runtime.run(fail, [], set())
    assert calls == ["sub", "pub"]
