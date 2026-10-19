"""Compatibility endpoint projections and stream lifetime with inert I/O boundaries."""

from __future__ import annotations

import asyncio
import functools
import inspect
import io
import json
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask, Response, has_request_context, jsonify, stream_with_context

from services import safety_contract
from services.api_core import bus_health, compat_health as health, system_info
from services.api_core.event_stream import EventCursor
from services.core import camera_state, resource_observation


@pytest.fixture
def context():
    return SimpleNamespace(
        Response=Response,
        jsonify=jsonify,
        json=json,
        stream_with_context=stream_with_context,
        time=SimpleNamespace(time=lambda: 100.25, sleep=Mock()),
        START_TS=10.0,
        LAST_MSG_TS=99.0,
        LAST_HEARTBEAT_TS=98.0,
        LAST_CAMERA={},
        LAST_XGO={"ts": 97.0},
        HIST_CPU=deque(),
        HIST_MEM=deque(),
        EVENTS=deque(),
        _ZMQ_OK=True,
        BUS_PUB_PORT=5555,
        BUS_SUB_PORT=5556,
        BASE_DIR="/inert-fixture",
        RAW_PATH="/inert-fixture/raw.jpg",
        _read_flags=lambda: {"estop": True, "motion_enable": False},
        os=SimpleNamespace(cpu_count=lambda: None, path=SimpleNamespace(isfile=lambda _path: False), stat=Mock()),
    )


def test_liveness_and_health_alias_keep_json_and_do_not_read_device_state(context):
    with Flask(__name__).app_context():
        response, status = health.health_alias(context)
    assert status == 200
    assert response.get_json() == {"ok": True}
    live = health.livez(context)
    assert live.mimetype == "application/json"
    assert live.get_json() == {"alive": True, "uptime_s": 90.25}


@pytest.mark.parametrize("failed", [set(), {"describe"}, {"rev-parse"}, {"describe", "rev-parse"}])
def test_version_git_queries_fail_independently_and_keep_fixed_arguments(context, failed):
    def check_output(command, **kwargs):
        assert kwargs == {"cwd": "/inert-fixture", "text": True, "timeout": 1.0}
        if command[1] in failed:
            raise OSError("inert git unavailable")
        return "  release-tag-dirty\n" if command[1] == "describe" else " abc1234\n"

    reader = Mock(side_effect=check_output)
    context.subprocess = SimpleNamespace(check_output=reader)
    context._git_info = functools.partial(health._git_info, context)
    result = health.api_version(context).get_json()
    assert result == {
        "name": "rider-pi",
        "api": "v2",
        "ts": 100,
        "git": {
            "describe": None if "describe" in failed else "release-tag-dirty",
            "commit": None if "rev-parse" in failed else "abc1234",
        },
    }
    assert [call.args[0] for call in reader.call_args_list] == [
        ["git", "describe", "--always", "--dirty", "--tags"],
        ["git", "rev-parse", "--short", "HEAD"],
    ]


@pytest.mark.parametrize("msg_at,executor_at,status", [(99.0, 100.0, 200), (None, 100.0, 503), (99.0, 90.0, 503)])
def test_readiness_uses_received_traffic_and_real_executor_age(context, monkeypatch, msg_at, executor_at, status):
    context.LAST_MSG_TS = msg_at
    monkeypatch.setattr(bus_health, "time", SimpleNamespace(time=lambda: 100.25))
    monkeypatch.setattr(
        safety_contract, "read_status", lambda: {"observed_at": executor_at, "instance_id": "fake-executor"}
    )
    response = health.readyz(context)
    payload = response.get_json()
    assert response.status_code == status
    assert payload["ready"] is (status == 200)
    assert payload["partial"] is (status != 200)
    assert payload["ports"] == {"pub": 5555, "sub": 5556}
    assert payload["components"]["executor"]["observed_at"] == executor_at
    assert health.api_bus_health(context).get_json() == payload


@pytest.fixture
def system_snapshot(context, monkeypatch):
    snapshot = {
        "cpu_pct": 12.5,
        "mem": {"pct": 22, "total": 1000, "used": 220},
        "load": {"1": 1.5, "5": 2.5, "15": 3.5},
    }

    def read(hist_cpu, hist_mem):
        assert hist_cpu is context.HIST_CPU
        assert hist_mem is context.HIST_MEM
        return snapshot

    monkeypatch.setattr(system_info, "get_sysinfo", read)
    return snapshot


@pytest.mark.usefixtures("system_snapshot")
def test_status_alias_keeps_cpu_fallback_and_unmodified_safety_flags(context):
    payload = health.api_status(context).get_json()
    assert payload == {
        "system": {"cpu": {"count": 1, "percent": 12.5}},
        "devices": {"summary": {"flags": {"estop": True, "motion_enable": False}}},
    }


@pytest.mark.usefixtures("system_snapshot")
@pytest.mark.parametrize(
    "raw,started,expected",
    [("25.75 0.0", 10.0, 25.75), (None, 10.0, 90.25), ("not a number", 10.0, 90.25), (None, 200.0, 0.0)],
)
def test_metrics_uses_proc_uptime_or_clamped_start_fallback(context, monkeypatch, raw, started, expected):
    def read_uptime(path):
        assert path == "/proc/uptime"
        if raw is None:
            raise OSError("inert proc unavailable")
        return io.StringIO(raw)

    context.START_TS = started
    monkeypatch.setattr(health, "open", read_uptime, raising=False)
    payload = health.api_metrics_alias(context).get_json()
    assert payload["cpu"] == {"count": 1, "percent": 12.5}
    assert payload["mem"] == {"percent": 22, "total": 1000, "used": 220}
    assert payload["load"] == {"1m": 1.5, "5m": 2.5, "15m": 3.5}
    assert payload["uptime"] == {"boot_time": int(100.25 - expected), "uptime_s": expected}


@pytest.mark.parametrize("present,last_seen", [(True, 80.0), (False, None)])
def test_device_aliases_keep_legacy_frame_path_without_inventing_a_file(context, monkeypatch, present, last_seen):
    context.LAST_MSG_TS = last_seen
    context.LAST_XGO = {"ts": last_seen}
    context.os.path.isfile = lambda path: present
    context.os.stat.return_value = SimpleNamespace(st_mtime=70.9)
    monkeypatch.setattr(camera_state, "status", lambda _unit: {"active": "inactive"})
    monkeypatch.setattr(resource_observation, "snapshot", lambda _name: {"free": True, "holders": []})
    devices = health.api_devices(context).get_json()
    frame = health.api_last_frame(context).get_json()
    expected_frame = {"exists": present, "mtime": 70 if present else None, "path": "data/last_frame.jpg"}
    assert frame == expected_frame
    assert devices["vision"]["last_frame"] == expected_frame
    assert devices["vision"]["running"] is False
    assert devices["bus"]["last_seen_ts"] == (80.0 if present else 100.25)
    assert devices["xgo"]["connected"] is present
    assert devices["flags"] == {"estop": True, "motion_enable": False}
    if not present:
        context.os.stat.assert_not_called()


def test_event_rows_keep_producer_time_and_recover_after_malformed_event(context):
    context.EVENTS.append({"not_json": {1}})
    waits = []

    def sleep(delay):
        waits.append(delay)
        if delay == 0.5:
            context.EVENTS.clear()
            context.EVENTS.append({"topic": "fixture", "observed_at": 7.0})

    context.time.sleep = sleep
    rows = health._event_rows(context, EventCursor)
    assert next(rows) == 'data: {"topic": "fixture", "observed_at": 7.0}\n\n'
    rows.close()
    assert waits == [1.0, 0.5, 1.0]
    assert inspect.getgeneratorstate(rows) == inspect.GEN_CLOSED


def test_events_keepalive_and_client_close_release_flask_stream_context(context):
    app = Flask(__name__)
    closed = []
    with app.test_request_context("/events"):
        response = health.events(context)
        response.call_on_close(lambda: closed.append(True))
        assert response.mimetype == "text/event-stream"
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Accel-Buffering"] == "no"
        assert next(response.response) == ": keepalive\n\n"
        assert context.time.sleep.call_count == 10
        response.close()
        assert closed == [True]
        assert inspect.getgeneratorstate(response.response) == inspect.GEN_CLOSED
        assert list(response.response) == []
    assert not has_request_context()


def test_stream_cancellation_propagates_and_closes_generator_context(context):
    context.time.sleep.side_effect = asyncio.CancelledError("inert stream cancelled")
    with Flask(__name__).test_request_context("/events"):
        response = health.events(context)
        try:
            with pytest.raises(asyncio.CancelledError, match="inert stream cancelled"):
                next(response.response)
        finally:
            response.close()
        assert inspect.getgeneratorstate(response.response) == inspect.GEN_CLOSED
    assert not has_request_context()
    context.time.sleep.assert_called_once_with(1.0)
