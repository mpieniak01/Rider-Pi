"""One-start preparation with real temporary orchestration locks and fake I/O."""

import copy
import json
import time

import pytest

from apps.safety.gate import MotionGate
from common.service_catalog import DEFAULT_REGISTRY
from services import navigation_config
from services.core.features import FeatureManager, NullPublisher
from services.navigation_trial import NavigationTrial, TrialError, public_status
from services.safety_contract import command_envelope


class World:
    def __init__(self, tmp_path):
        self.gate = MotionGate(blocked=lambda: False)
        self.active, self.actions, self.commands = set(), [], []
        self.hook = None
        self.elapsed = 0.0
        self.failure = None
        self.config_path = tmp_path / "navigation.json"
        policy = copy.deepcopy(navigation_config.DEFAULT)
        policy.update(verified=True, calibration_id="accepted", model_sha256="a" * 64)
        self.config_path.write_text(json.dumps(policy))
        self.manager = FeatureManager(
            registry={
                key: DEFAULT_REGISTRY[key]
                for key in ("s2_camera_preview", "s14_venom_navigation", "s15_venom_perception")
            },
            runner=self.run,
            status_fn=self.unit_status,
            publisher=NullPublisher(),
            safety_status=self.safety,
            safety_stop=lambda _: pytest.fail("A trial must never use global cleanup STOP"),
            dependency_check=lambda *_: [],
            producer_status=lambda _: {},
            state_path=tmp_path / "features.json",
        )
        self.trial = NavigationTrial(
            self.manager,
            safety=self.safety,
            submit=self.submit,
            settings=lambda: {"revision": 3},
            status=self.status,
            clock=lambda: self.elapsed,
            sleep=self.sleep,
        )

    def sleep(self, seconds):
        self.elapsed += seconds

    def safety(self):
        return {
            **self.gate.snapshot(),
            "ready": True,
            "stale": False,
            "can_move": self.gate.can_actuate(),
            "hardware_ready": True,
            "remote_decision_deadline_supported": True,
            "remote_decision_feedback_supported": True,
            "scoped_stop_generation_supported": True,
            "manual_settings": {"revision": 3},
            "capabilities": {name: {"available": True, "stop_verified": True} for name in ("move", "turn")},
        }

    def submit(self, payload):
        self.commands.append(dict(payload))
        command = command_envelope(payload)
        accepted, reason = self.gate.authorize(command)
        return {
            "ok": accepted,
            "confirmed": accepted,
            "error": None if accepted else reason,
            "ack": {"generation": self.gate.generation, "request_id": command["request_id"]},
            "safety": self.safety(),
        }, 200 if accepted else 409

    def unit_status(self, unit):
        return {
            "unit": unit,
            "load": "loaded",
            "active": "active" if unit in self.active else "inactive",
            "sub": "running" if unit in self.active else "dead",
        }

    def run(self, unit, action):
        self.actions.append((unit, action))
        if self.hook:
            self.hook(unit, action)
        if self.failure == (unit, action):
            return {"ok": False, "error": "fixture_start_failure"}
        if action == "start":
            self.active.add(unit)
        else:
            self.active.discard(unit)
        return {"ok": True, "unit": unit, "action": action}

    def status(self):
        intent = self.manager._intents.get("s14_venom_navigation", {})
        if not intent:
            return {}
        return {
            "run_id": "new-run",
            "mode": "drive",
            "running": True,
            "observed_at": time.time(),
            "config_revision": navigation_config.snapshot()["revision"],
            "generation": self.gate.generation,
            "operator_request_id": intent["request_id"],
            "sampled_monotonic": self.elapsed,
            "permit_remaining_ms": 150,
            "response_age_ms": 40,
        }

    def body(self, **changes):
        return {
            "request_id": "operator-click",
            "generation": self.gate.generation,
            "ts": time.time(),
            "ttl_ms": 500,
            "config_revision": navigation_config.snapshot()["revision"],
            "settings_revision": 3,
            "operator_consent": True,
            "operator_plan": "Forward, current low speed, up to 10 seconds.",
            "source": "manual",
            "execution_context": "panel",
            **changes,
        }

    def arm_manual(self):
        return self.submit(
            {
                "action": "arm",
                "source": "manual",
                "owner": "manual",
                "request_id": "new-manual",
                "generation": self.gate.generation,
                "seq": 0,
                "ts": time.time(),
                "ttl_ms": 500,
                "operator_consent": True,
                "operator_plan": "Manual operator takeover",
                "execution_context": "panel",
                "arming_mode": "operator",
            }
        )


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.delenv("MOTION_ENABLE", raising=False)
    monkeypatch.setenv("FEATURE_STATE_PATH", str(tmp_path / "features.json"))
    monkeypatch.setenv("RIDER_NAVIGATION_CONFIG", str(tmp_path / "navigation.json"))
    from services.core import feature_state, features, lcd_cleanup, resource_observation

    monkeypatch.setattr(features, "task_availability", lambda *_: {"start_available": True})
    monkeypatch.setattr(feature_state, "task_availability", lambda *_: {"start_available": True})
    monkeypatch.setattr(features.systemd_ctrl, "invalidate_snapshot", lambda: None)
    monkeypatch.setattr(resource_observation, "invalidate", lambda *_: None)
    monkeypatch.setattr(lcd_cleanup, "finish_lcd_stop", lambda _u, _a, result: result)
    return World(tmp_path)


def test_single_request_starts_with_one_arm_and_real_temp_flock(world):
    before = navigation_config.snapshot()
    result = world.trial.start(world.body())
    assert result["ok"] and result["status"]["run_id"] == "new-run"
    assert result["config"]["mode"] == "drive" and result["config"]["revision"] == before["revision"] + 1
    assert result["config"]["speed"] == before["speed"]
    assert result["config"]["max_motion_ms"] == before["max_motion_ms"]
    assert result["authority"]["owner"] == "navigation"
    assert len([row for row in world.commands if row["action"] == "arm"]) == 1
    assert world.commands[0]["lease_s"] == 10
    assert all(row["action"] != "move" for row in world.commands)
    assert "sampled_monotonic" not in result["status"]
    assert world.manager._state_path.with_suffix(".lock").is_file()
    assert world.manager._operation_guard is None
    intent = world.manager._intents["s14_venom_navigation"]
    assert intent["settings_revision"] == result["authority"]["manual_settings"]["revision"]


def test_existing_operator_arm_is_taken_over_once(world):
    assert world.arm_manual()[0]["ok"]
    initial = world.gate.generation
    result = world.trial.start(world.body())
    assert result["authority"]["owner"] == "navigation"
    own_arms = [row for row in world.commands if row["action"] == "arm" and row["owner"] == "navigation"]
    assert len(own_arms) == 1
    stop = next(row for row in world.commands if row["action"] == "stop")
    assert stop["expected_generation"] == initial


def test_replayed_request_does_not_arm_twice(world):
    body = world.body()
    world.trial.start(body)
    # Reproduce exact identifier with otherwise current explicit envelope.
    with pytest.raises(TrialError, match="navigation_trial_replay"):
        world.trial.start(world.body(request_id=body["request_id"]))
    assert len([row for row in world.commands if row["action"] == "arm"]) == 1


@pytest.mark.parametrize(
    "change,code",
    [
        ({"ts": 0}, "stale_or_invalid_operator_intent"),
        ({"ttl_ms": 501}, "stale_or_invalid_operator_intent"),
        ({"ttl_ms": True}, "stale_or_invalid_operator_intent"),
        ({"generation": "old"}, "navigation_trial_authority_changed"),
        ({"config_revision": 42}, "navigation_configuration_conflict"),
        ({"settings_revision": 4}, "manual_settings_stale"),
        ({"operator_consent": False}, "navigation_trial_consent_required"),
    ],
)
def test_invalid_admission_never_starts_services_or_arm(world, change, code):
    with pytest.raises(TrialError, match=code):
        world.trial.start(world.body(**change))
    assert not world.actions and not world.commands


def test_global_stop_during_prepare_cancels_without_later_arm(world):
    def stop_during_camera(_unit, action):
        if action == "start":
            world.gate.authorize({"action": "stop"})

    world.hook = stop_during_camera
    with pytest.raises(TrialError, match="navigation_trial_cancelled"):
        world.trial.start(world.body())
    assert not any(row["action"] == "arm" for row in world.commands)
    assert world.gate.state == "DISARMED"


def test_prepare_budget_is_not_extended_by_slow_camera(world):
    world.hook = lambda *_: setattr(world, "elapsed", 16.0)
    with pytest.raises(TrialError, match="navigation_trial_prepare_timeout"):
        world.trial.start(world.body())
    assert not world.commands


def test_rollback_after_new_manual_generation_does_not_stop_new_owner(world):
    def takeover(unit, action):
        if unit == "rider-venom-navigation.service" and action == "start":
            world.gate.authorize({"action": "stop"})
            assert world.arm_manual()[0]["ok"]

    world.hook = takeover
    with pytest.raises(TrialError, match="navigation_trial_cancelled"):
        world.trial.start(world.body())
    assert world.gate.owner == "manual" and world.gate.state == "ARMED"
    assert not any(row["action"] == "stop" for row in world.commands)
    assert len([row for row in world.commands if row["action"] == "arm" and row["owner"] == "navigation"]) == 1


def test_failed_start_after_own_arm_revokes_only_own_generation(world):
    world.failure = ("rider-venom-navigation.service", "start")
    with pytest.raises(TrialError, match="start_failed"):
        world.trial.start(world.body())
    assert world.gate.state == "DISARMED"
    assert any(row["action"] == "stop" and row.get("expected_generation") for row in world.commands)


def test_run_confirmation_rejects_previous_run_and_stops_own_arm(world):
    world.trial.status = lambda: {"running": True, "run_id": "previous"}
    with pytest.raises(TrialError, match="navigation_trial_prepare_timeout"):
        world.trial.start(world.body())
    assert world.gate.state == "DISARMED"


@pytest.mark.parametrize("action", ["stop", "disarm"])
def test_atomic_scoped_stop_cannot_revoke_new_manual_owner(world, action):
    previous = world.gate.generation
    world.gate.authorize({"action": "stop"})
    assert world.arm_manual()[0]["ok"]
    generation = world.gate.generation
    accepted, reason = world.gate.authorize({"action": action, "expected_generation": previous})
    assert not accepted and reason == "stale_stop_generation"
    assert world.gate.generation == generation and world.gate.owner == "manual"
    assert world.gate.authorize({"action": action})[0]
    assert world.gate.state == "DISARMED"


def test_public_status_decrements_relative_budget_on_pi():
    result = public_status(
        {
            "sampled_monotonic": 10.0,
            "permit_remaining_ms": 150,
            "response_age_ms": 80,
        },
        sampled_now=10.1,
    )
    assert result["permit_remaining_ms"] == pytest.approx(50)
    assert result["decision_age_ms"] == pytest.approx(180)
    assert "sampled_monotonic" not in result
    assert public_status(result, fresh=False)["permit_remaining_ms"] == 0


def test_trial_http_route_uses_same_domain_and_contract(world, monkeypatch):
    from flask import Flask

    from services.api_core import features_api, rider_routes
    from services.api_core.contract_registry import contract_for

    monkeypatch.setattr(features_api, "feature_manager", world.manager)
    app = Flask(__name__)
    app.extensions["rider_navigation_trial"] = world.trial
    rider_routes.register_compute(app)
    response = app.test_client().post("/api/navigation/trial", json=world.body())
    assert response.status_code == 200 and response.json["ok"]
    assert response.json["status"]["run_id"] == "new-run"
    assert contract_for("/api/navigation/trial").name == "rider.navigation_loop"


def test_status_api_projects_pi_local_remaining_and_hides_monotonic(world, monkeypatch, tmp_path):
    from flask import Flask

    from services.api_core import navigation_api

    path = tmp_path / "navigation_status.json"
    monkeypatch.setenv("RIDER_NAVIGATION_STATUS", str(path))
    path.write_text(
        json.dumps(
            {
                "observed_at": time.time(),
                "running": True,
                "sampled_monotonic": time.monotonic() - 0.1,
                "permit_remaining_ms": 150,
                "response_age_ms": 80,
            }
        )
    )
    app = Flask(__name__)
    app.add_url_rule("/status", view_func=navigation_api.status_handler)
    response = app.test_client().get("/status")
    assert response.status_code == 200
    assert 0 < response.json["permit_remaining_ms"] <= 50
    assert response.json["decision_age_ms"] >= 180
    assert "sampled_monotonic" not in response.json


def test_prepared_intent_is_accepted_by_real_navigation_runner(world, monkeypatch):
    from apps.compute import navigation
    from apps.safety.intent import read_service_intent

    result = world.trial.start(world.body())
    intent = read_service_intent("rider-venom-navigation.service", world.gate.generation)
    assert intent["settings_revision"] == 3
    monkeypatch.setattr(navigation, "read_status", world.safety)
    monkeypatch.setattr(
        navigation,
        "selected_executor",
        lambda: {
            "device_id": "fixture",
            "url": "http://127.0.0.1:18880",
            "token": "fixture-only",
        },
    )
    monkeypatch.setattr(navigation, "write_intent_status", lambda *_a, **_k: True)
    runner = navigation.NavigationRunner(clock=lambda: world.elapsed)
    assert runner._authority()
    assert runner.intent["request_id"] == intent["request_id"]
    assert runner.generation == result["authority"]["generation"]
    assert not any(row["action"] == "move" for row in world.commands)


def test_mode_switch_preserves_unrelated_voice_compute_consumer(world):
    world.manager._state_path.write_text(json.dumps({"requested": ["s13_venom_voice"]}))
    old = navigation_config.snapshot()
    switched = navigation_config.configure({"revision": old["revision"], "values": {"mode": "drive"}})
    assert switched["mode"] == "drive" and switched["speed"] == old["speed"]
    with pytest.raises(ValueError, match="compute_stop_goals_first"):
        navigation_config.configure({"revision": switched["revision"], "values": {"speed": 0.11}})


@pytest.mark.parametrize("goal", ["s14_venom_navigation", "s15_venom_perception"])
def test_mode_switch_still_requires_its_navigation_consumers_to_stop(world, goal):
    world.manager._state_path.write_text(json.dumps({"requested": [goal]}))
    with pytest.raises(ValueError, match="navigation_stop_goals_first"):
        navigation_config.configure({"revision": 0, "values": {"mode": "drive"}})


def test_trial_replaces_running_observation_without_extra_arm(world):
    assert world.manager.set_feature("s15_venom_perception", True)["ok"]
    result = world.trial.start(world.body())
    assert result["ok"] and "s15_venom_perception" not in world.manager._requested
    assert "s14_venom_navigation" in world.manager._requested
    assert len([row for row in world.commands if row["action"] == "arm"]) == 1


def test_trial_replaces_old_navigation_with_scoped_stop_and_one_new_arm(world):
    config = navigation_config.configure({"revision": 0, "values": {"mode": "drive"}})
    assert world.submit(
        {
            "action": "arm",
            "owner": "navigation",
            "source": "manual",
            "request_id": "old-arm",
            "generation": world.gate.generation,
            "seq": 0,
            "ts": time.time(),
            "ttl_ms": 500,
            "operator_consent": True,
            "operator_plan": "Old bounded test",
            "lease_s": 10,
        }
    )[0]["ok"]
    old_generation = world.gate.generation
    assert world.manager.set_feature(
        "s14_venom_navigation",
        True,
        control={
            "request_id": "old-start",
            "source": "navigation",
            "generation": old_generation,
            "seq": 1,
            "ts": time.time(),
            "ttl_ms": 500,
            "settings_revision": 3,
        },
    )["ok"]
    before = len(world.commands)
    result = world.trial.start(world.body(config_revision=config["revision"]))
    assert result["ok"] and result["authority"]["generation"] != old_generation
    commands = world.commands[before:]
    assert len([row for row in commands if row["action"] == "arm"]) == 1
    assert commands[0]["action"] == "stop"
    assert commands[0]["expected_generation"] == old_generation


def test_unconfirmed_queued_arm_is_cancelled_before_it_can_execute(world):
    original = world.submit
    queued = []

    def pending_arm(payload):
        if payload["action"] == "arm":
            queued.append(dict(payload))
            return {"ok": False, "pending": True, "error": "executor_ack_pending"}, 202
        return original(payload)

    world.trial.submit = pending_arm
    before = world.gate.generation
    with pytest.raises(TrialError, match="executor_ack_pending"):
        world.trial.start(world.body())
    assert len(queued) == 1
    assert world.gate.generation != before and world.gate.state == "DISARMED"
    accepted, reason = world.gate.authorize(queued[0])
    assert not accepted and reason == "stale_generation"
    assert not any(unit == "rider-venom-navigation.service" for unit, _ in world.actions)


@pytest.mark.parametrize("error_type", [RuntimeError, TypeError])
def test_unexpected_error_after_arm_revokes_own_permission_without_exposing_text(world, error_type):
    def failed_status():
        raise error_type("private backend details must not reach the operator")

    world.trial.status = failed_status
    with pytest.raises(TrialError, match="navigation_trial_prepare_failed") as caught:
        world.trial.start(world.body())
    assert str(caught.value) == "navigation_trial_prepare_failed"
    assert caught.value.status == 503
    assert caught.value.details["preparation"]["phase"] == "start_navigation"
    assert "private backend" not in json.dumps(caught.value.details)
    assert world.gate.state == "DISARMED"
    assert any(row["action"] == "stop" and row.get("expected_generation") for row in world.commands)


@pytest.mark.parametrize("error_type", [RuntimeError, TypeError])
def test_unexpected_error_after_new_manual_arm_cannot_revoke_new_operator(world, error_type):
    def takeover_then_fail():
        world.gate.authorize({"action": "stop"})
        assert world.arm_manual()[0]["ok"]
        raise error_type("private backend details must not reach the operator")

    world.trial.status = takeover_then_fail
    with pytest.raises(TrialError, match="navigation_trial_prepare_failed"):
        world.trial.start(world.body())
    assert world.gate.state == "ARMED" and world.gate.owner == "manual"
    assert not any(row["action"] == "stop" for row in world.commands)


@pytest.mark.parametrize("capability", ["remote_decision_deadline_supported", "scoped_stop_generation_supported"])
def test_old_executor_is_rejected_before_preparation_or_arm(world, capability):
    original = world.trial.safety

    def legacy():
        row = original()
        row.pop(capability)
        return row

    world.trial.safety = legacy
    with pytest.raises(TrialError, match="navigation_executor_update_required"):
        world.trial.start(world.body())
    assert not world.actions and not world.commands


def test_new_manual_command_during_preparation_cancels_old_trial_without_rearming(world):
    assert world.arm_manual()[0]["ok"]

    def newer_intent(unit, action):
        if unit.startswith("camera-capture") and action == "start":
            command = command_envelope(
                {
                    "action": "move",
                    "source": "manual",
                    "generation": world.gate.generation,
                    "execution_context": "panel",
                    "request_id": "newer-arrow",
                    "seq": world.gate.last_seq + 1,
                    "ts": time.time(),
                    "ttl_ms": 500,
                    "vx": 0.1,
                    "duration": 0.1,
                }
            )
            assert world.gate.authorize(command)[0]

    world.hook = newer_intent
    with pytest.raises(TrialError, match="navigation_trial_cancelled"):
        world.trial.start(world.body())
    assert world.gate.owner == "manual" and world.gate.state == "ARMED"
    assert not any(row.get("owner") == "navigation" for row in world.commands)


@pytest.mark.parametrize("status_cost", [0.005, 0.025, 0.05])
def test_warm_observation_to_trial_keeps_camera_and_feed_with_service_latency(world, status_cost):
    assert world.manager.set_feature("s15_venom_perception", True)["ok"]
    assert world.arm_manual()[0]["ok"]
    original = world.manager.status_fn
    calls = []

    def slow_status(unit):
        calls.append(unit)
        world.elapsed += status_cost
        return original(unit)

    world.manager.status_fn = slow_status
    world.actions.clear()
    world.commands.clear()
    result = world.trial.start(world.body())
    assert result["ok"]
    assert world.elapsed < 5.0
    assert len(calls) < 80
    assert not any(unit in {"camera-capture@raw.service", "frame-distributor.service"} for unit, _ in world.actions)
    assert len([c for c in world.commands if c["action"] == "arm"]) == 1
    assert result["preparation"]["state"] == "completed"
    assert result["preparation"]["phase"] == "ready"


def test_failed_producer_handoff_keeps_passive_camera_without_new_arm(world):
    assert world.manager.set_feature("s15_venom_perception", True)["ok"]
    assert world.arm_manual()[0]["ok"]
    world.failure = ("rider-venom-perception.service", "stop")
    world.actions.clear()
    world.commands.clear()
    with pytest.raises(TrialError) as caught:
        world.trial.start(world.body())
    assert not any(c["action"] == "arm" for c in world.commands)
    assert world.gate.owner == "manual"
    assert "s2_camera_preview" in world.manager._requested
    assert not any(unit in {"camera-capture@raw.service", "frame-distributor.service"} for unit, _ in world.actions)
    progress = caught.value.details["preparation"]
    assert progress["phase"] == "stop_old_producer"
    assert progress["state"] == "failed"
    saved = json.loads(world.manager._state_path.with_name("navigation_trial_prepare.json").read_text())
    assert saved["request_id"] == "operator-click" and saved["state"] == "failed"


def test_delayed_first_status_reports_phase_and_revokes_only_trial_authority(world):
    world.trial.status = lambda: {}
    with pytest.raises(TrialError, match="navigation_trial_prepare_timeout") as caught:
        world.trial.start(world.body())
    assert caught.value.details["preparation"]["phase"] == "first_status"
    assert world.gate.state == "DISARMED"
    assert "s2_camera_preview" in world.manager._requested
    assert "s14_venom_navigation" not in world.manager._requested


def test_preparation_status_is_visible_even_without_a_producer_file(world, monkeypatch):
    from flask import Flask

    from services.api_core.navigation_api import status_handler

    target = world.manager._state_path.with_name("navigation_loop.json")
    monkeypatch.setenv("RIDER_NAVIGATION_STATUS", str(target))
    world.hook = lambda *_: setattr(world, "elapsed", 16.0)
    with pytest.raises(TrialError):
        world.trial.start(world.body())
    app = Flask(__name__)
    with app.test_request_context():
        response, code = status_handler()
    assert code == 200
    data = response.get_json()
    assert data["stale"] is True
    assert data["preparation"]["state"] == "failed"
    assert data["preparation"]["phase"] == "camera_reservation"
    assert data["preparation"]["fresh"] is True


@pytest.mark.parametrize("payload", [{}, [], {"observed_at": float("nan")}, {"observed_at": "invalid"}])
def test_invalid_preparation_snapshot_does_not_break_status(world, payload):
    from services.navigation_trial import preparation_status

    target = world.manager._state_path.with_name("navigation_trial_prepare.json")
    target.write_text(json.dumps(payload))
    assert preparation_status(target) is None


def test_panel_trial_http_runs_real_orchestration_without_restarting_warm_camera(world, monkeypatch):
    from flask import Flask

    from services.api_core import features_api, navigation_api

    assert world.manager.set_feature("s15_venom_perception", True)["ok"]
    assert world.arm_manual()[0]["ok"]
    world.actions.clear()
    world.commands.clear()
    original_status = world.status
    samples = []

    def delayed_status():
        samples.append(True)
        return {} if len(samples) < 3 else original_status()

    world.trial.status = delayed_status
    monkeypatch.setattr(features_api, "feature_manager", world.manager)
    app = Flask(__name__)
    app.extensions["rider_navigation_trial"] = world.trial
    app.add_url_rule("/api/navigation/trial", view_func=navigation_api.trial_handler, methods=["POST"])
    with app.test_client() as client:
        response = client.post("/api/navigation/trial", json=world.body())
    data = response.get_json()
    assert response.status_code == 200, data
    assert data["status"]["operator_request_id"].endswith("-start")
    assert data["authority"]["owner"] == "navigation"
    assert data["preparation"]["state"] == "completed"
    assert len(samples) == 3
    assert len([c for c in world.commands if c["action"] == "arm"]) == 1
    assert not any(unit in {"camera-capture@raw.service", "frame-distributor.service"} for unit, _ in world.actions)
    assert not any(c["action"] == "move" for c in world.commands)


def test_production_trial_that_ended_during_start_is_not_reported_as_never_started(world):
    # Real case: own run reached GO and decision_timeout before start HTTP
    # returned at 5835ms. The timing packet, not an ideal ready response, drives
    # the late-return hook. No hardware/backend subprocess is used.
    from pathlib import Path

    packet = json.loads((Path(__file__).parent / "fixtures/navigation/production_1245_timing.json").read_text())
    final = packet["rows"][-1]
    saved = {}
    original = world.status

    def delayed_start(unit, action):
        if unit == "rider-venom-navigation.target" and action == "start":
            saved.update(original())
            saved.update(running=False, latched=True, stop_reason=final["stop_reason"])
            world.elapsed = packet["prepare_elapsed_ms"] / 1000

    world.hook = delayed_start
    world.trial.status = lambda: dict(saved)
    with pytest.raises(TrialError, match="navigation_trial_stopped") as caught:
        world.trial.start(world.body())
    assert caught.value.details["started"] is True
    assert caught.value.details["status"]["stop_reason"] == "decision_timeout"
    assert caught.value.details["status"]["operator_request_id"].endswith("-start")
    assert caught.value.details["preparation"]["error"] == "navigation_trial_stopped"
    assert world.gate.state == "DISARMED"


def test_slow_http_bookkeeping_cannot_cancel_a_fresh_run_started_within_budget(world):
    saved = {}
    original = world.status

    def slow_after_process_start(unit, action):
        if unit == "rider-venom-navigation.target" and action == "start":
            world.elapsed = 5.83528
            saved.update(original())
            saved.update(run_started_monotonic=2.0, sampled_monotonic=world.elapsed)

    world.hook = slow_after_process_start
    world.trial.status = lambda: dict(saved)
    result = world.trial.start(world.body())
    assert result["ok"] and result["status"]["running"]
    assert result["preparation"]["elapsed_ms"] > 5000
    assert len([c for c in world.commands if c["action"] == "arm"]) == 1
    assert not any(c["action"] == "stop" for c in world.commands)


def test_run_started_after_prepare_deadline_is_not_accepted(world):
    saved = {}
    original = world.status

    def too_late(unit, action):
        if unit == "rider-venom-navigation.target" and action == "start":
            world.elapsed = 5.83528
            saved.update(original())
            saved.update(run_started_monotonic=5.5, sampled_monotonic=world.elapsed)

    world.hook = too_late
    world.trial.status = lambda: dict(saved)
    with pytest.raises(TrialError, match="navigation_trial_prepare_timeout"):
        world.trial.start(world.body())
    assert world.gate.state == "DISARMED"


@pytest.mark.parametrize(
    "field,value",
    [
        ("operator_request_id", "another-operator-start"),
        ("generation", "another-generation"),
        ("config_revision", -1),
    ],
)
def test_late_unrelated_producer_outcome_does_not_replace_prepare_failure(world, field, value):
    saved = {}
    original = world.status

    def unrelated(unit, action):
        if unit == "rider-venom-navigation.target" and action == "start":
            saved.update(original())
            saved.update(running=False, latched=True, stop_reason="decision_timeout")
            saved[field] = value
            world.elapsed = 5.83528

    world.hook = unrelated
    world.trial.status = lambda: dict(saved)
    with pytest.raises(TrialError, match="navigation_trial_prepare_timeout") as caught:
        world.trial.start(world.body())
    assert not caught.value.details.get("started")


def test_idempotent_stop_uses_observed_task_result_in_negotiated_contract(world, monkeypatch):
    from flask import Flask

    from services.api_core import features_api, http_contract

    monkeypatch.setattr(features_api, "feature_manager", world.manager)
    app = Flask(__name__)
    http_contract.install(app, after_request=True)
    app.add_url_rule("/api/logic/feature/<name>", view_func=features_api.feature_handler, methods=["POST"])
    with app.test_client() as client:
        response = client.post(
            "/api/logic/feature/s14_venom_navigation",
            json={"enabled": False},
            headers={"Accept": "application/vnd.rider.api+json;version=1"},
        )
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    assert data["operation"]["status"] == "executed"
    assert data["operation"]["actuation"] is False
    assert not world.commands


def test_public_status_does_not_present_expired_go_as_an_active_motor_permit():
    source = {
        "sampled_monotonic": 10.0,
        "run_started_monotonic": 9.0,
        "mode": "drive",
        "running": True,
        "latched": False,
        "permit_remaining_ms": 80,
        "feedback_remaining_ms": 240,
        "decision": {"action": "go", "vision_action": "go"},
    }
    row = public_status(source, sampled_now=10.1)
    assert row["permit_remaining_ms"] == 0
    assert row["feedback_remaining_ms"] == 140
    assert row["waiting_feedback"] and row["paused"]
    assert row["decision"]["action"] == "stop"
    assert row["decision"]["vision_action"] == "go"
    assert source["decision"]["action"] == "go"
    assert "run_started_monotonic" not in row
