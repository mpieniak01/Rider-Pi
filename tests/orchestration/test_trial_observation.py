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
