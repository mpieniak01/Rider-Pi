"""Integrated routes with injected telemetry and publisher; no hardware I/O."""

import json
import time
from collections import deque

import pytest

from services.api_core import compat, compat_health, devices, navigation_state, navigator_api, service_logs, state_api


@pytest.fixture
def client(monkeypatch):
    from services.api_server import app

    monkeypatch.setattr(compat, "LAST_XGO", {})
    monkeypatch.setattr(compat, "LAST_NAVIGATOR", {})
    monkeypatch.setattr(navigation_state, "_rows", {"map": None, "pose": None, "path": None})
    monkeypatch.setattr(state_api, "load_obstacle", lambda: None)
    for name in ("start_bus_sub", "start_xgo_ro", "start_lcd_idle_guard", "_get_bus_pub"):
        monkeypatch.setattr(compat, name, lambda: pytest.fail("Read must not acquire a device or BUS"))
    return app.test_client()


def test_devices_page_and_log_route_are_readonly(client, monkeypatch):
    response = client.get("/devices")
    assert response.status_code == 200
    assert b'data-page="devices"' in response.data
    calls = []
    monkeypatch.setattr(
        service_logs, "read_logs", lambda unit: calls.append(unit) or {"ok": True, "unit": unit, "lines": ["fixture"]}
    )
    response = client.get("/api/services/rider-camera.service/logs")
    assert response.status_code == 200
    assert calls == ["rider-camera.service"]
    assert response.headers["Cache-Control"] == "no-store"
    assert client.post("/api/services/rider-camera.service/logs").status_code == 405


def test_state_and_navigation_status_preserve_producer_time_and_identity(client, monkeypatch):
    observed = time.time() - 4
    assert navigation_state.observe("robot.pose", {"x": 0, "y": 0, "theta": 0, "observed_at": observed})
    devices.observe_navigator(
        {
            "active": True,
            "state": "EXPLORING",
            "generation": "fixture-generation",
            "request_id": "fixture-request",
            "observed_at": observed,
            "ts": time.time(),
            "navigation_ready": False,
            "data_error": "uncalibrated",
        }
    )
    monkeypatch.setattr(navigator_api, "read_status", lambda: {"state": "DISARMED"})
    state = client.get("/state").get_json()
    assert state["navigation"]["pose"]["observed_at"] == observed
    assert state["navigation"]["pose"]["stale"] is True
    status = client.get("/api/navigator/status").get_json()
    assert status["request_id"] == "fixture-request" and status["generation"] == "fixture-generation"
    assert status["observed_at"] == observed and status["stale"] is True
    assert status["navigation_ready"] is False and status["data_error"] == "uncalibrated"
    assert status["navigation"]["pose"]["x"] == 0


@pytest.mark.parametrize("topic", ["devices.xgo.roll", "xgo.roll", "motion.bridge.telemetry.roll"])
def test_legacy_sensor_subtopics_preserve_zero_null_and_original_time(monkeypatch, topic):
    cache = {"roll": 42, "ts": time.time()}
    monkeypatch.setattr(compat, "LAST_XGO", cache)
    observed = time.time() - 20
    assert devices.observe_xgo(topic, {"value": 0, "observed_at": observed})
    assert cache["roll"] == 0 and cache["ts"] == observed
    assert devices.observe_xgo(topic, {"value": None, "observed_at": observed})
    assert cache["roll"] is None
    assert devices.observe_xgo(topic, 0)
    assert cache["roll"] == 0 and cache["observed_at"] is None and cache["stale"] is True


def test_missing_or_invalid_time_does_not_confirm_old_navigation(monkeypatch):
    monkeypatch.setattr(compat, "LAST_NAVIGATOR", {})
    for ts in (None, float("nan"), True, 10**1000):
        devices.observe_navigator({"active": False, "state": "IDLE", "ts": ts})
        assert compat.LAST_NAVIGATOR["observed_at"] is None
        assert compat.LAST_NAVIGATOR["stale"] is True


@pytest.mark.parametrize("flags", [{"stale": True}, {"offline": True}])
def test_state_sensor_projection_does_not_hide_explicit_unknown(client, flags):
    observed = time.time()
    devices.observe_xgo(
        "devices.xgo", {"roll": 0, "battery_pct": 0, "observed_at": observed, "source": "fixture", **flags}
    )
    row = client.get("/state").get_json()["devices"]["xgo"]
    assert row["roll"] == 0 and row["observed_at"] == observed and row["source"] == "fixture"
    assert row["stale"] is True
    assert row["battery_pct"] == 0


def test_real_compat_publisher_accepts_navigation_keyword_without_restamping(client, monkeypatch):
    calls = []

    class Publisher:
        def publish(self, topic, payload, *, add_ts):
            calls.append((topic, dict(payload), add_ts))

    observed = time.time()
    envelope = {
        "request_id": "fixture",
        "generation": "fixture-generation",
        "source": "manual",
        "seq": 2,
        "ts": observed,
        "ttl_ms": 500,
    }
    monkeypatch.setattr(compat, "_get_bus_pub", lambda: Publisher())
    monkeypatch.setattr(navigator_api, "authorize_request", lambda body: (dict(body), {"state": "ARMED"}))
    response = client.post("/api/navigator/start", json=envelope)
    assert response.status_code == 202 and response.get_json()["confirmed"] is False
    assert len(calls) == 1 and calls[0][0] == "navigator.control" and calls[0][2] is False
    assert calls[0][1]["ts"] == observed and calls[0][1]["request_id"] == "fixture"
    with pytest.raises(ValueError, match="timestamps"):
        compat.bus_pub("fixture", {}, add_ts=True)


def test_events_wrapper_uses_live_rotating_buffer(client, monkeypatch):
    first, second = {"topic": "fixture.one", "ts": 5}, {"topic": "fixture.two", "ts": 4}
    events = deque([first], maxlen=1)
    monkeypatch.setattr(compat, "EVENTS", events)
    monkeypatch.setattr(compat.time, "sleep", lambda _duration: None)
    with compat.app.test_request_context("/events"):
        response = compat.events()
        stream = iter(response.response)
        assert json.loads(next(stream).removeprefix("data: ")) == first
        events.append(second)
        assert json.loads(next(stream).removeprefix("data: ")) == second
        response.close()
    assert compat.events.__module__ == "services.api_core.compat"
    assert callable(compat_health.events)
