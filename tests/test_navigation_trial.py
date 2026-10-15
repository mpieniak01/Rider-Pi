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
    world.hook = lambda *_: setattr(world, "elapsed", 6.0)
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
    assert caught.value.status == 503 and caught.value.details is None
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
