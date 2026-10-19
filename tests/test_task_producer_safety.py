"""Task authorization, observation freshness and BUS framing without hardware."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from apps.motion.tracking_controller import TrackingController
from apps.navigator import main as navigation, motion as producer
from apps.safety import state as snapshots
from apps.safety.intent import read_service_intent, write_intent_status
from common.bus import BusSub


def intent(generation="current"):
    return {"generation": generation, "request_id": "explicit-task", "seq": 3, "ts": time.time() - 0.1}


def controller(*, authorization=None, state=None, writer=None):
    sent = []
    state = state or {"can_move": True, "owner": "follow_me", "generation": "current", "last_seq": 3}
    instance = TrackingController(
        bus=SimpleNamespace(publish=lambda *args, **kw: sent.append((args, kw))),
        status_reader=lambda: state,
        intent_reader=lambda unit, generation: authorization,
        intent_writer=writer or (lambda *args, **kw: True),
    )
    return instance, sent, state


def test_arm_alone_cannot_enable_stale_tracking_producer():
    ctrl, sent, _ = controller()
    ctrl.on_tracking_offset(0.5, "face", observed_at=time.time())
    assert sent == []


def test_current_intent_accepts_fresh_target_with_original_generation():
    ctrl, sent, _ = controller(authorization=intent())
    ctrl.on_tracking_offset(0.5, "face", observed_at=time.time())
    command = sent[0][0][1]
    assert command["generation"] == "current" and command["source"] == "follow_me"
    assert command["seq"] > 3 and command["duration"] <= 0.25


@pytest.mark.parametrize("observed", [None, float("nan"), float("inf"), 1, "future"])
def test_invalid_or_old_observation_is_never_restamped(observed):
    # Collection can precede this test by more than 100 seconds in the full suite.
    if observed == "future":
        observed = time.time() + 100
    ctrl, sent, _ = controller(authorization=intent())
    ctrl.on_tracking_offset(0.5, "face", observed_at=observed)
    assert sent == []


def test_observation_from_before_task_start_is_refused():
    auth = intent()
    auth["ts"] = time.time()
    ctrl, sent, _ = controller(authorization=auth)
    ctrl.on_tracking_offset(0.5, "face", observed_at=auth["ts"] - 0.05)
    assert sent == []


def test_failed_producer_status_sends_only_stop():
    ctrl, sent, _ = controller(authorization=intent(), writer=lambda *args, **kw: False)
    ctrl.on_tracking_offset(0.5, "face", observed_at=time.time())
    assert [record[0][1]["action"] for record in sent] == ["stop"]


def test_waiting_for_target_acknowledges_intent_without_actuation():
    records = []
    ctrl, sent, _ = controller(authorization=intent(), writer=lambda *args, **kw: records.append((args, kw)) or True)
    ctrl.watchdog_tick()
    assert len(records) == 1 and records[0][1]["active"] is True and sent == []


def test_intent_reader_refuses_previous_generation(tmp_path, monkeypatch):
    path = tmp_path / "feature_state.json"
    monkeypatch.setenv("FEATURE_STATE_PATH", str(path))
    path.write_text(json.dumps({"service_intents": {"rider-tracking-controller.service": intent("old")}}))
    assert read_service_intent("rider-tracking-controller.service", "new") is None
    assert read_service_intent("rider-tracking-controller.service", "old")["request_id"] == "explicit-task"


def test_producer_status_has_distinct_atomic_file(tmp_path, monkeypatch):
    monkeypatch.setenv("FEATURE_STATE_PATH", str(tmp_path / "feature_state.json"))
    assert write_intent_status("rider-navigator.service", intent(), active=True)
    row = json.loads((tmp_path / "rider-navigator.service.json").read_text())
    assert row["accepted"] is True and row["active"] is True
    assert row["generation"] == "current" and row["observed_at"] <= time.time()
    assert not write_intent_status("../../outside", intent(), active=True)


def test_producer_restart_cannot_replay_claimed_task(tmp_path, monkeypatch):
    monkeypatch.setenv("FEATURE_STATE_PATH", str(tmp_path / "feature_state.json"))
    task = intent()
    assert write_intent_status("rider-navigator.service", task, active=False)
    monkeypatch.setattr("apps.safety.intent._PRODUCER_INSTANCE", "restarted-process")
    assert not write_intent_status("rider-navigator.service", task, active=True)
    task["request_id"] = "new-explicit-task"
    assert write_intent_status("rider-navigator.service", task, active=True)
    row = json.loads((tmp_path / "rider-navigator.service.json").read_text())
    assert row["instance_id"] == "restarted-process" and isinstance(row["pid"], int)


@pytest.mark.parametrize(
    "field,value",
    [
        ("ready", "true"),
        ("hardware_ready", "true"),
        ("lease_remaining_s", float("nan")),
        ("lease_remaining_s", float("inf")),
        ("lease_remaining_s", "30"),
        ("lease_remaining_s", -1),
        ("lease_remaining_s", True),
    ],
)
def test_bad_snapshot_cannot_grant_motion(tmp_path, monkeypatch, field, value):
    path = tmp_path / "status.json"
    monkeypatch.setenv("MOTION_STATE_PATH", str(path))
    state = {
        "contract_version": 1,
        "state": "ARMED",
        "ready": True,
        "hardware_ready": True,
        "can_move": True,
        "lease_remaining_s": 30,
        "observed_at": time.time(),
        field: value,
    }
    path.write_text(json.dumps(state))
    result = snapshots.read_status()
    assert result["can_move"] is False and result["read_only"] is True


@pytest.mark.parametrize(
    "frames,topic",
    [
        ([b'motion.command {"action":"stop"}'], "motion.command"),
        ([b"motion.command", b'{"action":"stop"}'], "motion.command"),
    ],
)
def test_supported_bus_frame_shapes(frames, topic):
    sub = object.__new__(BusSub)
    sub.sock = SimpleNamespace(recv_multipart=lambda: frames)
    assert sub.recv() == (topic, {"action": "stop"})


def navigator(monkeypatch, *, authorization=None, owner="navigation"):
    sent = []
    state = {"state": "ARMED", "can_move": True, "owner": owner, "generation": "current", "last_seq": 3}
    monkeypatch.setattr(navigation, "BusPub", lambda **kw: SimpleNamespace(publish=lambda *a, **kw: sent.append(a)))
    monkeypatch.setattr(navigation, "BusSub", lambda *a, **kw: SimpleNamespace())
    monkeypatch.setattr("apps.safety.state.read_status", lambda: state)
    monkeypatch.setattr("services.safety_contract.read_status", lambda: state)
    monkeypatch.setattr(producer, "read_service_intent", lambda *a: authorization)
    monkeypatch.setattr(producer, "write_intent_status", lambda *a, **kw: True)
    return navigation.Navigator(), sent, state


def test_navigator_requires_task_intent_before_start(monkeypatch):
    nav, sent, _ = navigator(monkeypatch)
    nav._consume_task_intent()
    assert not nav.active and sent == []


def test_navigator_consumes_intent_once_and_stops_on_lost_lease(monkeypatch):
    nav, sent, state = navigator(monkeypatch, authorization=intent())
    nav._consume_task_intent()
    nav._handle_obstacle_sample({"observed_at": time.time(), "present": False, "confidence": 0.8})
    nav._consume_task_intent()
    moves = [data for topic, data in sent if topic == "motion.command" and data["action"] == "move"]
    assert moves == []  # Clear pixels cannot manufacture physical geometry or HOME.
    assert not nav.navigation_quality()["navigation_ready"]
    state["can_move"] = False
    nav._consume_task_intent()
    assert not nav.active and sent[-1][1]["action"] == "stop"


def test_navigator_status_failure_cannot_publish_move(monkeypatch):
    nav, sent, _ = navigator(monkeypatch, authorization=intent())
    monkeypatch.setattr(producer, "write_intent_status", lambda *a, **kw: False)
    nav._consume_task_intent()
    assert not nav.active
    assert [data["action"] for topic, data in sent if topic == "motion.command"] == ["stop"]


def test_stale_navigator_cleanup_cannot_stop_new_generation(monkeypatch):
    nav, sent, state = navigator(monkeypatch)
    nav._motion_generation = "previous"
    nav._send_motion_stop()
    assert sent == []


def test_stopped_navigator_does_not_report_active_task(monkeypatch):
    nav, sent, _ = navigator(monkeypatch, authorization=intent())
    nav._consume_task_intent()
    nav.state = navigation.NavigatorState.STOPPED
    nav.active = False
    nav._intent_status_at = 0
    recorded = []
    monkeypatch.setattr(producer, "write_intent_status", lambda *a, **kw: recorded.append(kw) or True)
    nav._consume_task_intent()
    assert recorded[-1]["active"] is False


@pytest.mark.parametrize("bad", [True, -0.01, 1.01, float("inf"), float("nan"), [], {}])
def test_navigator_bad_config_has_no_partial_effect(monkeypatch, bad):
    nav, sent, state = navigator(monkeypatch)
    state["state"] = "DISARMED"
    old = (nav.strategy, nav.fwd_speed, nav.turn_speed)
    nav._handle_control_command({"action": "config", "config": {"strategy": "AVOID", "fwd_speed": bad}})
    assert (nav.strategy, nav.fwd_speed, nav.turn_speed) == old and sent == []


def test_navigator_config_is_denied_while_armed(monkeypatch):
    nav, sent, _ = navigator(monkeypatch)
    nav._handle_control_command({"action": "config", "config": {"strategy": "AVOID"}})
    assert nav.strategy == navigation.Strategy.STOP and sent == []
