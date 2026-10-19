"""Canonical motion aliases/producers use fake BUS and Flask clients only."""

import json

import pytest
from flask import Flask
from motion_fakes import arm, command, executor

from common.bus import BusPub
from common.motion_commands import canonical_command, normalize_control
from services.motion_cmd_shim import translate


def envelope(**extra):
    return {
        "generation": "original",
        "source": "manual",
        "seq": 7,
        "request_id": "id",
        "ts": 100,
        "ttl_ms": 200,
        **extra,
    }


@pytest.mark.parametrize(
    "direction,axis,expected", [("fwd", "vx", 0.3), ("back", "vx", -0.3), ("left", "yaw", -0.3), ("right", "yaw", 0.3)]
)
def test_legacy_http_bus_and_retired_shim_are_same_pure_aliases(direction, axis, expected):
    original = envelope(cmd="drive", dir=direction, v=0.3, t=0.2)
    http = normalize_control(original)
    assert http == canonical_command("motion.cmd", original) == translate(original)
    assert http[axis] == expected
    assert all(http[key] == value for key, value in envelope().items())
    assert original["cmd"] == "drive"
    assert "action" not in original


def test_missing_legacy_metadata_is_never_manufactured():
    row = canonical_command("cmd.move", {"dir": "forward"})
    assert not set(envelope()) & row.keys()
    assert canonical_command("cmd.stop", {}) == {"action": "stop"}


@pytest.mark.parametrize(
    "topic", ["motion.command", "cmd.move", "cmd.height", "calibration.activate", "odometry.reference"]
)
def test_bus_helper_never_adds_command_timestamp(topic):
    class Socket:
        def send_multipart(self, frames):
            self.frames = frames

    bus = object.__new__(BusPub)
    bus.prefix, bus.sock = "", Socket()
    bus.publish(topic, {"source": "manual"}, add_ts=True)
    assert json.loads(bus.sock.frames[1]) == {"source": "manual"}


@pytest.mark.parametrize("method", ["get", "head", "options"])
def test_stop_read_or_preflight_never_dispatches(monkeypatch, method):
    from services import web_motion_bridge
    from services.api_core import control_api, control_proxy

    monkeypatch.setattr(control_api, "submit_control", lambda *args: pytest.fail("read must not send STOP"))
    monkeypatch.setattr(web_motion_bridge, "submit_control", lambda *args: pytest.fail("read must not send STOP"))
    app = Flask(__name__)
    app.add_url_rule("/legacy", view_func=control_api.api_stop, methods=["GET", "HEAD", "POST", "OPTIONS"])
    app.add_url_rule("/proxy", view_func=control_proxy.proxy_stop_get, methods=["GET", "HEAD"])
    for client, path in [(app.test_client(), "/legacy"), (web_motion_bridge.app.test_client(), "/api/stop")]:
        response = getattr(client, method)(path)
        assert response.status_code == (204 if method == "options" else 405)
    if method != "options":
        assert getattr(app.test_client(), method)("/proxy").status_code == 405


def test_post_stop_stays_explicit_and_requires_no_arm(monkeypatch):
    from services import web_motion_bridge

    sent = []
    monkeypatch.setattr(web_motion_bridge, "submit_control", lambda row: (sent.append(row) or {"pending": True}, 202))
    response = web_motion_bridge.app.test_client().post("/api/stop", json={"request_id": "explicit"})
    assert response.status_code == 202
    assert sent == [{"action": "stop", "request_id": "explicit"}]


def test_nlu_only_proposes_motion_and_never_renews_input_time():
    from apps.nlu.main import proposal

    topic, row = proposal({"observed_at": None, "ts": 999}, {"type": "drive", "dir": "forward", "v": 0.2})
    assert topic == "motion.intent"
    assert not row["actuation"]
    assert not row["executable"]
    assert row["observed_at"] is None
    assert "generation" not in row
    topic, row = proposal({"observed_at": 100}, {"type": "stop"})
    assert topic == "motion.command"
    assert row["action"] == "stop"
    assert row["ts"] == 100
    assert row["request_id"]
    assert "generation" not in row


def test_choreographer_cannot_create_authority_but_face_still_works():
    from apps.choreographer.main import execute_action

    sent = []

    class Publisher:
        def publish(self, topic, payload, **kwargs):
            sent.append((topic, payload, kwargs))

    for topic in ["motion.command", "motion", "cmd.balance", "odometry.reference", "calibration.activate"]:
        execute_action(Publisher(), {"topic": topic, "payload": {"action": "arm"}})
        assert sent[-1][0] == "motion.intent"
        assert not sent[-1][1]["executable"]
        assert sent[-1][2] == {"add_ts": False}
    execute_action(Publisher(), {"topic": "command.face.expression", "payload": {"expression": "happy"}})
    assert sent[-1][0] == "command.face.expression"


def test_old_accepted_sdk_write_does_not_adopt_new_gate_generation(executor):
    instance, _ = executor
    old = dict(instance.sdk_output())
    arm(instance)
    assert instance.sdk_output()["generation"] == old["generation"]
    assert instance.sdk_output()["observed_at"] == old["observed_at"]
    instance.apply(command(instance))
    instance.tick(0.02)
    assert instance.sdk_output()["generation"] == instance.gate.generation
    assert instance.sdk_output()["physical_completion"] == "unverified"
