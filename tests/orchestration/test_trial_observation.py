"""Replay the real Pi systemd batch latency, without any hardware connection."""

import json
from unittest.mock import Mock

import pytest
from test_navigation_trial import world as world

from common.service_catalog import DEFAULT_REGISTRY, UNIT_CATALOG, task_units
from services.core import feature_observation


def test_observer_reads_only_requested_units_and_reuses_status_contract(monkeypatch):
    run = Mock(
        return_value=Mock(
            returncode=0,
            stderr="",
            stdout="Id=rider-venom-navigation.service\nLoadState=loaded\nActiveState=active\nMainPID=42\n",
        )
    )
    monkeypatch.setattr(feature_observation.subprocess, "run", run)
    rows = feature_observation.read_units(("rider-venom-navigation.service",), timeout=0.4)
    command = run.call_args.args[0]
    assert command[2:-2] == ["rider-venom-navigation.service"]
    assert run.call_args.kwargs["timeout"] == 0.4
    assert rows["rider-venom-navigation.service"]["pid"] == 42
    assert rows["rider-venom-navigation.service"]["active"] == "active"
    assert not rows["rider-venom-navigation.service"]["stale"]


def test_failed_observation_is_unknown_not_permission(monkeypatch):
    import subprocess

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 0.01)

    monkeypatch.setattr(feature_observation.subprocess, "run", timeout)
    rows = feature_observation.read_units(("rider-venom-navigation.service",), timeout=0)
    row = rows["rider-venom-navigation.service"]
    assert row["stale"] and row["error"]
    assert row["active"] == "unknown" and not row["installed"]


def test_real_catalog_warm_handoff_uses_scoped_reads_and_current_journal(world, monkeypatch):
    # Production 2026-10-15: 42-unit reads took 460/470/476 ms;
    # the nine navigation members took 76/76/77 ms. Model batch overhead,
    # not an invented per-unit delay. Only I/O/actuation boundaries are replaced.
    world.manager.registry = DEFAULT_REGISTRY
    world.manager._requested["s0_core"] = {}
    world.active.update(task_units(DEFAULT_REGISTRY["s0_core"], {}))
    world.manager.set_feature("s15_venom_perception", True)
    world.actions.clear()
    world.elapsed = 0.0
    world.manager.status_fn = None
    reads, journal_at_start = [], []

    def observe(units, *, timeout):
        reads.append(units)
        world.elapsed += 0.476 if len(units) == len(UNIT_CATALOG) else 0.10
        return {unit: world.unit_status(unit) for unit in units}

    monkeypatch.setattr(feature_observation, "read_units", observe)
    original = world.run

    def run(unit, action):
        world.elapsed += 0.18
        if unit == "rider-venom-navigation.service" and action == "start":
            journal_at_start.append(json.loads(world.manager._state_path.read_text()))
        return original(unit, action)

    world.manager.runner = run
    result = world.trial.start(world.body())
    assert result["ok"]
    assert 0 < world.elapsed < 5.0
    assert reads and all(len(units) < len(UNIT_CATALOG) for units in reads)
    assert ("rider-venom-perception.target", "stop") in world.actions
    assert not any(unit.startswith("camera-capture@") and action == "stop" for unit, action in world.actions)
    assert journal_at_start
    intent = journal_at_start[0]["service_intents"]["rider-venom-navigation.service"]
    assert intent["generation"] == world.gate.generation
    assert intent["request_id"] == world.manager._intents["s14_venom_navigation"]["request_id"]
    final = json.loads(world.manager._state_path.read_text())
    rows = {row["name"]: row for row in final["features"]}
    assert rows["s14_venom_navigation"]["requested"]
    assert not rows["s15_venom_perception"]["requested"]
    assert world.manager._operation_units == ()
    assert world.manager._operation_status_cache is None
    progress = json.loads(world.manager._state_path.with_name("navigation_trial_prepare.json").read_text())
    assert progress["state"] == "completed"
    assert progress["phase_timings_ms"]["start_navigation"] >= 0


def test_scoped_snapshot_retains_active_voice_and_does_not_refresh_unrelated_goals(world):
    world.manager.registry = DEFAULT_REGISTRY
    world.manager._requested["s5_voice"] = {"domain": "asr"}
    world.manager._states["s5_voice"] = "starting"
    world.manager._started_at["s5_voice"] = 0.0
    with world.manager.operation(guard=lambda: None, remaining=lambda: 5, stop=lambda _: {}):
        assert world.manager._persist_state()
        state = json.loads(world.manager._state_path.read_text())
        voice = next(row for row in state["features"] if row["name"] == "s5_voice")
        assert voice["requested"] and voice["options"]["domain"] == "asr"
        assert "rider-voice-web.service" in voice["members"]
        assert voice["state"] in {"starting", "partial"}
        assert not any(row["name"] == "s9_tracking" for row in state["features"])


def test_observer_rejects_unknown_unit_before_subprocess(monkeypatch):
    run = Mock()
    monkeypatch.setattr(feature_observation.subprocess, "run", run)
    with pytest.raises(ValueError):
        feature_observation.read_units(("not-catalogued.service",), timeout=1)
    run.assert_not_called()


def test_failed_start_clears_pending_intent_and_requested_projection(world):
    world.failure = ("rider-venom-navigation.service", "start")
    from services.navigation_trial import TrialError

    with pytest.raises(TrialError):
        world.trial.start(world.body())
    saved = json.loads(world.manager._state_path.read_text())
    row = next(row for row in saved["features"] if row["name"] == "s14_venom_navigation")
    assert not row["requested"]
    assert "rider-venom-navigation.service" not in saved["service_intents"]
    assert "s14_venom_navigation" not in saved["requested"]


def test_dependency_failure_updates_the_affected_stopped_row(world):
    world.manager._snapshot_rows = [world.manager._describe("s15_venom_perception")]
    world.manager.dependency_check = lambda *_: ["missing_profile_module"]
    with world.manager.operation(guard=lambda: None, remaining=lambda: 5, stop=lambda _: {}):
        result = world.manager.set_feature("s15_venom_perception", True)
    assert result["error"] == "runtime_dependencies_missing"
    saved = json.loads(world.manager._state_path.read_text())
    row = next(row for row in saved["features"] if row["name"] == "s15_venom_perception")
    assert not row["requested"]
    assert row["state"] == "failed"
    assert row["error"] == "runtime_dependencies_missing"
    assert not world.actions


@pytest.mark.parametrize("delay", [0.50343, 1.0])
def test_click_accepted_before_internal_restore_does_not_expire(world, monkeypatch, delay):
    import time
    from contextlib import contextmanager

    base = time.time()

    def wall():
        return base + world.elapsed

    monkeypatch.setattr(time, "time", wall)
    world.trial.wall = wall
    world.gate.wall_clock = wall
    operation = world.manager.operation

    @contextmanager
    def restore_delay(**kwargs):
        with operation(**kwargs):
            world.elapsed += delay
            yield

    world.manager.operation = restore_delay
    result = world.trial.start(world.body())
    assert result["ok"]
    assert len([row for row in world.commands if row["action"] == "arm"]) == 1


def test_new_manual_command_while_click_waits_cancels_preparation(world):
    from contextlib import contextmanager

    from services.navigation_trial import TrialError

    world.arm_manual()
    operation = world.manager.operation

    @contextmanager
    def intervening_manual(**kwargs):
        with operation(**kwargs):
            world.gate.last_seq += 1
            yield

    world.manager.operation = intervening_manual
    before = len(world.commands)
    with pytest.raises(TrialError, match="navigation_trial_authority_changed"):
        world.trial.start(world.body())
    assert len(world.commands) == before
    assert not world.actions


def test_old_executor_cannot_arm_feedback_wait_trial(world):
    from services.navigation_trial import TrialError

    safety = world.trial.safety

    def old_executor():
        row = safety()
        row.pop("remote_decision_feedback_supported")
        return row

    world.trial.safety = old_executor
    with pytest.raises(TrialError, match="navigation_executor_update_required"):
        world.trial.start(world.body())
    assert not world.commands and not world.actions


def orphan_world(world):
    world.manager.set_feature("s2_camera_preview", True)
    world.active.add("rider-venom-navigation.target")
    original = world.unit_status

    def status(unit):
        row = original(unit)
        return {**row, "pid": 0, "wants": [], "requires": []}

    world.manager.status_fn = status
    world.actions.clear()


def test_production_failed_producer_leaves_empty_target_and_next_click_recovers(world):
    orphan_world(world)
    result = world.trial.start(world.body())
    assert result["ok"]
    assert ("rider-venom-navigation.target", "stop") in world.actions
    assert not any(unit.startswith("camera-") and action == "stop" for unit, action in world.actions)
    assert len([command for command in world.commands if command["action"] == "arm"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"wants": ["rider-venom-navigation.service"]},
        {"requires": ["external.service"]},
        {"stale": True},
        {"pid": 42},
    ],
)
def test_target_with_unknown_ownership_or_dependencies_is_not_adopted(world, change):
    from services.navigation_trial import TrialError

    orphan_world(world)
    original = world.manager.status_fn

    def status(unit):
        row = original(unit)
        return {**row, **change} if unit == "rider-venom-navigation.target" else row

    world.manager.status_fn = status
    with pytest.raises(TrialError, match="external_services_running"):
        world.trial.start(world.body())
    assert not any(action == "stop" for _, action in world.actions)
    assert not world.commands


def test_privileged_empty_target_cleanup_does_not_revoke_generation(monkeypatch):
    from common import service_action_guard
    from services import safety_contract
    from services.core import feature_cleanup

    monkeypatch.setattr(feature_cleanup, "inactive_navigation_target", lambda unit: True)

    def forbidden():
        pytest.fail("Empty target cleanup must not submit another global STOP")

    monkeypatch.setattr(safety_contract, "request_stop", forbidden)
    result = service_action_guard.check("rider-venom-navigation.target", "stop")
    assert result["ok"] and result["effects"] == ["empty_navigation_target_stop"]


@pytest.mark.parametrize("running", [False, True])
def test_privileged_cleanup_repeats_process_and_dependency_observation(monkeypatch, running):
    from services.core import feature_cleanup, feature_observation

    def read(units, **kwargs):
        return {
            units[0]: {"load": "loaded", "pid": 0, "wants": [], "requires": []},
            units[1]: {"load": "loaded", "pid": 42 if running else 0, "active": "active" if running else "failed"},
        }

    monkeypatch.setattr(feature_observation, "read_units", read)
    assert feature_cleanup.inactive_navigation_target("rider-venom-navigation.target") is (not running)


def test_navigation_bookkeeping_finishes_before_producer_can_move(world):
    observed = []

    def startup(unit, action):
        if action == "start" and unit == "rider-venom-navigation.target":
            assert "rider-venom-navigation.service" not in world.active
            world.elapsed += 2.0
            observed.append("target")
        elif action == "start" and unit == "rider-venom-navigation.service":
            assert observed == ["target"]
            world.elapsed += 0.5
            observed.append("producer")

    world.hook = startup
    result = world.trial.start(world.body())
    assert result["ok"]
    assert observed == ["target", "producer"]
    assert world.actions[-1] == ("rider-venom-navigation.service", "start")
    assert not any(command["action"] == "stop" for command in world.commands)


def test_failed_navigation_target_never_starts_movement_producer(world):
    from services.navigation_trial import TrialError

    world.failure = ("rider-venom-navigation.target", "start")
    with pytest.raises(TrialError):
        world.trial.start(world.body())
    assert ("rider-venom-navigation.service", "start") not in world.actions
    assert world.gate.state == "DISARMED"


def test_real_service_preparation_can_take_seven_seconds_without_extending_arm(world):
    def costs(unit, action):
        if action == "start" and unit == "camera-capture@raw.service":
            world.elapsed += 3.0
        if action == "start" and unit == "rider-venom-navigation.target":
            world.elapsed += 2.0
        if action == "start" and unit == "rider-venom-navigation.service":
            world.elapsed += 2.0

    world.hook = costs
    result = world.trial.start(world.body())
    assert result["ok"] and world.elapsed == 7.0
    arms = [row for row in world.commands if row["action"] == "arm"]
    assert len(arms) == 1 and arms[0]["lease_s"] == 10.0
