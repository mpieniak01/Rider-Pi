"""Admission precedence and lifecycle characterizations, using memory-only fakes."""

import copy
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from motion_fakes import Clock, arm, command, executor as executor

from apps.compute import navigation
from apps.motion import manual_settings as settings
from apps.motion.actuator_contract import validate_actuator
from common.motion_commands import canonical_command, normalize_control, protected_topic
from services.navigation_config import DEFAULT


@pytest.mark.parametrize(
    "fields,reason",
    [
        ({"mode": "unsupported", "settings_revision": -1, "vx": False}, "unsupported_motion_mode"),
        ({"mode": "hold", "settings_revision": -1}, "hold_operator_panel_only"),
        ({"settings_revision": -1, "vx": False, "generation": "old"}, "manual_settings_stale"),
        ({"vx": False, "generation": "old"}, "invalid_vx"),
        ({"generation": "old"}, "stale_generation"),
    ],
)
def test_executor_rejection_precedence_does_not_consume_authority_or_write_sdk(executor, fields, reason):
    instance, _ = executor
    arm(instance)
    before = instance.gate.generation, instance.gate.last_seq, instance.gate.owner, instance.gate.state
    calls = list(instance.adapter.calls)
    assert instance.apply(command(instance, **fields))["reason"] == reason
    assert (instance.gate.generation, instance.gate.last_seq, instance.gate.owner, instance.gate.state) == before
    assert instance.adapter.calls == calls
    assert instance.pending is None


def test_panel_rejection_precedes_agent_mode_and_settings(executor, monkeypatch):
    instance, _ = executor
    before = instance.gate.generation, instance.gate.last_seq, list(instance.adapter.calls)
    monkeypatch.setattr(instance.gate, "panel_rejection", lambda _: "invalid_panel_id")
    ack = instance.apply(command(instance, mode="unsupported", source="agent", settings_revision=-1))
    assert ack["reason"] == "invalid_panel_id"
    assert (instance.gate.generation, instance.gate.last_seq, instance.adapter.calls) == before


def test_operator_replay_and_conflict_never_authorize_again(executor, monkeypatch):
    instance, _ = executor
    payload = command(instance, "navigation_pause")
    first = instance.apply(payload)
    before = instance.gate.generation, instance.gate.last_seq, list(instance.adapter.calls)
    monkeypatch.setattr(instance.gate, "authorize", lambda _: pytest.fail("replay consumed authority"))
    replay = instance.apply(payload)
    assert replay["operator_replay"] is True
    assert (replay["status"], replay["reason"], replay["generation"]) == (
        first["status"],
        first["reason"],
        first["generation"],
    )
    conflict = instance.apply({**payload, "seq": payload["seq"] + 1})
    assert conflict["reason"] == "operator_request_conflict"
    assert (instance.gate.generation, instance.gate.last_seq, instance.adapter.calls) == before


def test_pending_goal_completion_and_transport_failure_order(executor, monkeypatch):
    instance, _ = executor
    arm(instance)
    first = command(instance, request_id="first")
    assert instance.apply(first)["status"] == "accepted"
    second = command(instance, request_id="second")
    assert instance.apply(second)["status"] == "accepted"
    assert instance.recent_acks[-1]["reason"] == "goal_superseded"
    assert instance.recent_acks[-1]["superseded_by"] == "second"

    def fail(_dt):
        raise OSError("fake transport")

    monkeypatch.setattr(instance.controller, "tick", fail)
    instance.tick(0.02)
    assert instance.gate.state == "DISARMED"
    assert instance.pending is None
    assert instance.adapter.calls[-1] == ("stop",)
    assert instance.last_ack["request_id"] == "second"
    assert instance.last_ack["status"] == "rejected"
    assert instance.error == "actuator_transport_failed:OSError"


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"action": "turn_left", "speed": 0.4, "ms": 80}, {"action": "move", "vx": 0, "yaw": -0.4, "duration": 0.08}),
        ({"direction": "down", "v": -0.3}, {"action": "move", "vx": -0.3, "yaw": 0, "duration": 0.1}),
        ({"action": "move", "direction": "left", "vx": 0.2}, {"action": "move", "vx": 0.2, "yaw": 0, "duration": 0.1}),
        ({"action": "move", "device_settings": True, "direction": "right"}, {"action": "move", "direction": "right"}),
    ],
)
def test_alias_values_preserve_envelope_and_input(payload, expected):
    envelope = {"source": "manual", "generation": "old", "seq": 3, "ts": 1.5, "ttl_ms": 50, "request_id": "id"}
    data = {**payload, **envelope}
    original = copy.deepcopy(data)
    result = normalize_control(data)
    assert data == original
    assert all(result[k] == v for k, v in {**expected, **envelope}.items())
    assert protected_topic("cmd.motion.turn_left")
    assert canonical_command("cmd.motion.stop", data)["action"] == "stop"


@pytest.mark.parametrize(
    "payload,reason",
    [
        ({"action": "move", "device_settings": True, "direction": "invalid", "vx": 1}, "invalid direction"),
        (
            {"action": "move", "device_settings": True, "direction": "left", "duration": 0.1},
            "device_settings_ambiguous_command",
        ),
        ({"action": "move", "direction": "bad", "ms": True}, "invalid direction"),
        ({"action": "move", "direction": "forward", "speed": True, "ms": True}, "speed must be numeric"),
        ({"action": "move", "ms": True}, "ms must be numeric"),
    ],
)
def test_alias_validation_precedence(payload, reason):
    with pytest.raises(ValueError, match=reason):
        normalize_control(payload)


@pytest.mark.parametrize(
    "payload,reason",
    [
        ({"action": "move", "vx": False, "yaw": False}, "invalid_vx"),
        ({"action": "move", "vx": 0, "yaw": False}, "invalid_yaw"),
        ({"action": "move", "vx": 2, "duration": None}, "duration_required"),
        ({"action": "move", "vx": 2, "duration": 0.1}, "motion_limits_exceeded"),
        ({"action": "balance", "enabled": 1}, "enabled_boolean_required"),
        ({"action": "action", "action_id": True}, "unsupported_action"),
    ],
)
def test_actuator_validation_error_order(payload, reason):
    with pytest.raises(ValueError, match=reason):
        validate_actuator(payload)


def test_actuator_duration_bound_depends_on_complete_device_context():
    payload = {"action": "move", "vx": 0.1, "duration": 0.75, "device_settings": True, "direction": "forward"}
    with pytest.raises(ValueError, match="motion_limits_exceeded"):
        validate_actuator(payload)
    assert validate_actuator({**payload, "source": "manual", "execution_context": "panel"})["duration"] == 0.75
    assert validate_actuator({"action": "action", "action_id": 255}) == {"name": "default"}
    assert validate_actuator({"action": "stop"}) == {}


@pytest.fixture
def memory_settings(monkeypatch):
    values = settings.defaults()
    row = settings._canonical(
        {"schema_version": 2, "revision": 7, "values": values, "directions": settings.direction_defaults(values)}
    )
    writes = []
    monkeypatch.setattr(settings, "locked", lambda: nullcontext())
    monkeypatch.setattr(settings, "read", lambda: copy.deepcopy(row))
    monkeypatch.setattr(settings, "_atomic", lambda data: writes.append(copy.deepcopy(data)))
    return row, writes


def test_settings_direction_precedence_and_no_input_mutation(memory_settings):
    row, _ = memory_settings
    original = copy.deepcopy(row)
    edits = {"forward": {"minimum": 0.8, "maximum": 0.1, "step": -1}}
    with pytest.raises(ValueError, match="manual_settings_direction_range"):
        settings._updated(row, {}, edits)
    assert row == original
    directions = copy.deepcopy(row["directions"])
    directions["forward"].update(speed=-1, duration=2)
    with pytest.raises(ValueError, match="manual_settings_direction_step_or_duration"):
        settings.validate_directions(directions, row["values"])


def test_settings_canonical_legacy_clamping_and_profile_validation_order(memory_settings):
    row, _ = memory_settings
    old = {k: row["values"][k] for k in settings.FIELDS}
    old.update(linear_speed=0.9, speed_limit=0.4)
    migrated = settings._canonical({"revision": 1, "values": old})
    assert migrated["values"]["linear_speed"] == 0.4
    assert migrated["values"]["linear_deceleration"] == old["linear_rate"]
    with pytest.raises(ValueError, match="manual_profile_id"):
        settings._canonical({**row, "profiles": {"invalid": {}}, "active_profile": "missing"})
    with pytest.raises(ValueError, match="manual_settings_fields"):
        settings.validate({**row["values"], "unrecognized": 1})


def test_profile_transaction_admission_precedes_callback_and_atomic_commit(memory_settings):
    row, writes = memory_settings
    checks = []
    with pytest.raises(ValueError, match="manual_settings_conflict"):
        settings.manage_profile({}, -1, validate_state=lambda: checks.append("checked"))
    assert checks == []
    with pytest.raises(ValueError, match="manual_profile_operation"):
        settings.manage_profile({}, row["revision"], validate_state=lambda: checks.append("checked"))
    assert checks == ["checked"]
    with pytest.raises(ValueError, match="manual_profile_not_found"):
        settings.manage_profile({"action": "save", "id": "missing"}, row["revision"], patch=False)
    assert writes == []
    created = settings.manage_profile({"action": "create", "name": "  Mock only  "}, row["revision"])
    assert created["revision"] == row["revision"] + 1
    assert created["profiles"][created["active_profile"]]["name"] == "Mock only"
    assert writes == [created]
    assert row["profiles"] == {}


@pytest.fixture
def navigation_memory(monkeypatch):
    clock = Clock()
    policy = {**DEFAULT, "mode": "drive", "verified": True, "calibration_id": "fake", "model_sha256": "a" * 64}
    safety = {
        "remote_decision_deadline_supported": True,
        "remote_decision_feedback_supported": True,
        "scoped_stop_generation_supported": True,
        "can_move": True,
        "owner": "navigation",
        "generation": "g",
        "last_seq": 2,
        "manual_settings": {"revision": 3},
        "calibration": {"profile_digest": "d"},
    }
    intent = {"request_id": "intent", "generation": "g", "seq": 1, "settings_revision": 3}
    claims, submissions = [], []
    monkeypatch.setattr(navigation.navigation_config, "snapshot", lambda: dict(policy))
    monkeypatch.setattr(navigation, "selected_executor", lambda: {"id": "fake"})
    monkeypatch.setattr(navigation, "read_status", lambda: dict(safety))
    monkeypatch.setattr(navigation, "read_service_intent", lambda *_: dict(intent))
    monkeypatch.setattr(navigation, "write_intent_status", lambda *a, **kw: claims.append((a, kw)) or True)
    monkeypatch.setattr(
        navigation, "submit_control", lambda data, **kw: submissions.append(data) or ({"ok": True}, 200)
    )
    runner = navigation.NavigationRunner(clock=clock)
    return runner, clock, safety, intent, claims, submissions


def test_navigation_ack_rejection_precedes_timeout_and_intent_claim(navigation_memory):
    runner, clock, safety, intent, claims, submissions = navigation_memory
    runner.pending_motion_acks[runner.run_id + "-old"] = clock() - 1
    safety.update(
        last_ack={"request_id": runner.run_id + "-rejected", "status": "rejected", "reason": "stale_generation"},
        can_move=False,
    )
    intent["settings_revision"] = -1
    with pytest.raises(navigation.ComputeError, match="navigation_motion_rejected"):
        runner._authority()
    assert claims == submissions == []
    assert runner.generation is None
    assert runner.intent is None
    assert runner.motion_failure["reason"] == "stale_generation"


def test_navigation_pending_ack_acceptance_then_settings_loss_does_not_adopt(navigation_memory):
    runner, clock, safety, intent, claims, submissions = navigation_memory
    key = runner.run_id + "-pending"
    runner.pending_motion_acks[key] = clock() - 1
    safety["last_ack"] = {"request_id": key, "status": "executed", "accepted": True}
    intent["settings_revision"] = -1
    with pytest.raises(navigation.ComputeError, match="navigation_settings_stale"):
        runner._authority()
    assert runner.pending_motion_acks == {}
    assert claims == submissions == []
    assert runner.generation is None
    assert runner.motion_sequence == -1


def test_navigation_expired_decision_rejects_before_sequence_or_submit(navigation_memory):
    runner, clock, _, _, claims, submissions = navigation_memory
    runner._authority()
    previous = runner.motion_sequence
    runner.lease.deadline = clock()
    with pytest.raises(navigation.ComputeError, match="navigation_decision_expired_before_submit"):
        runner.drive(0.1, 0.1)
    assert runner.motion_sequence == previous
    assert submissions == []
    assert len(claims) == 2


def test_navigation_pending_submission_keeps_exact_envelope(navigation_memory, monkeypatch):
    runner, clock, _, _, _, submissions = navigation_memory
    monkeypatch.setattr(
        navigation, "submit_control", lambda data, **kw: submissions.append((data, kw)) or ({"pending": True}, 202)
    )
    runner.lease.deadline, runner.lease.feedback_deadline = clock() + 0.1, clock() + 0.2
    runner.motion_publisher = object()
    runner.drive(0.12, 0.08, yaw=-0.2)
    payload, kwargs = submissions[0]
    assert payload['seq'] == 3
    assert payload['generation'] == 'g'
    assert payload['vx'] == 0.12
    assert payload['yaw'] == -0.2
    assert payload["decision_deadline_monotonic"] == clock() + 0.1
    assert kwargs == {"publisher": runner.motion_publisher, "timeout_s": 0.0}
    assert runner.pending_motion_acks == {payload["request_id"]: clock() + 0.1}


def test_navigation_generation_change_during_inference_prevents_decision_apply(navigation_memory, monkeypatch):
    runner, clock, _, _, _, submissions = navigation_memory
    runner.generation = "before"
    runner.sequence = 3
    runner.operator_lifecycle = SimpleNamespace(enabled=True)
    statuses = []
    monkeypatch.setattr(runner, "_status", statuses.append)
    monkeypatch.setattr(runner, "_startup_reply_expired", lambda *_: False)
    monkeypatch.setattr(runner.lease, "accept", lambda *_: pytest.fail("stale inference actuated"))

    def authority():
        runner.generation = "after"
        return True

    monkeypatch.setattr(runner, "_authority", authority)
    accepted, _ = runner._apply_decision({"action": "go", "state": "clear"}, {"frame_id": "f"}, clock())
    assert not accepted
    assert statuses == [None]
    assert submissions == []


def test_navigation_run_closes_fake_resources_after_startup_rejection(navigation_memory, monkeypatch):
    runner, _, _, _, _, _ = navigation_memory
    from apps.compute import stream_prepare

    events = []
    runner.source_factory = lambda: SimpleNamespace(close=lambda: events.append("source_closed"))
    runner.publisher_factory = lambda: SimpleNamespace(close=lambda: events.append("publisher_closed"))
    monkeypatch.setattr(stream_prepare, "prepare_stream", lambda **_: None)
    monkeypatch.setattr(
        runner, "_authority", lambda: (_ for _ in ()).throw(navigation.ComputeError("navigation_authority_lost"))
    )
    monkeypatch.setattr(runner, "_status", lambda _: events.append("status"))
    assert runner.run() == 2
    assert events == ["status", "source_closed", "publisher_closed"]
    assert runner.closed.is_set()
    assert runner.motion_publisher is None
