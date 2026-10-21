"""New mission admission reuses the production preparation transaction, never hardware."""

import json
import time

import pytest
from journey_fakes import policy
from test_navigation_trial import world as world

from services.navigation_journey import NavigationJourney
from services.navigation_trial import TrialError
from services.safety_contract import command_envelope


@pytest.fixture
def journey(world, monkeypatch):
    from apps.compute import stream_prepare

    monkeypatch.setattr(stream_prepare, "prepare_stream", lambda **_kwargs: None)
    config = policy()
    config["mode"] = "observe"
    world.config_path.write_text(json.dumps(config))
    previous_status = world.status

    def status():
        row = previous_status()
        return {**row, "journey": {**world.gate.journey.snapshot(), "maneuver_epoch": 0}} if row else row

    starter = NavigationJourney(
        world.manager,
        safety=world.safety,
        submit=world.submit,
        settings=lambda: {"revision": 3},
        status=status,
        clock=lambda: world.elapsed,
        sleep=world.sleep,
    )
    body = world.body(journey_version=1, operator_control_version=1, panel_id="operator")
    return world, starter, body


def test_one_explicit_start_prepares_journey_without_timed_lease(journey):
    world, starter, body = journey
    result = starter.start(body)
    assert result["ok"]
    arm = next(row for row in world.commands if row["action"] == "arm")
    assert arm["arming_mode"] == "journey"
    assert arm["journey_id"] == body["request_id"]
    assert "lease_s" not in arm
    assert result["status"]["journey"]["active"] is True
    assert result["authority"]["navigation_journey_version"] == 1
    assert all(row["action"] != "move" for row in world.commands)


@pytest.mark.parametrize(
    "change",
    [{"journey_version": True}, {"journey_version": 2}, {"panel_id": ""}, {"operator_control_version": None}],
)
def test_invalid_journey_optin_never_starts_services_or_arms(journey, change):
    world, starter, body = journey
    with pytest.raises(TrialError):
        starter.start({**body, **change})
    assert world.actions == world.commands == []


@pytest.mark.parametrize("field,value", [("enabled", False), ("protocol_version", 2), ("sweep_verified", False)])
def test_avoidance_must_be_accepted_before_any_preparation(journey, field, value):
    world, starter, body = journey
    config = policy()
    config["mode"] = "observe"
    config["avoidance"][field] = value
    world.config_path.write_text(json.dumps(config))
    with pytest.raises(TrialError, match="navigation_journey_avoidance_required"):
        starter.start(body)
    assert world.actions == world.commands == []


def test_missing_ground_calibration_is_reported_before_camera_or_arm(journey):
    world, starter, body = journey
    config = policy()
    config["mode"] = "observe"
    config["avoidance"]["geometry"]["mode"] = "ground"
    world.config_path.write_text(json.dumps(config))
    with pytest.raises(TrialError, match="navigation_geometry_calibration_required"):
        starter.start(body)
    assert world.actions == world.commands == []


def test_old_executor_capability_cannot_start_journey(journey):
    world, starter, body = journey
    original = starter.safety
    starter.safety = lambda: {**original(), "navigation_journey_version": None}
    with pytest.raises(TrialError, match="navigation_journey_update_required"):
        starter.start(body)
    assert world.actions == world.commands == []


def test_trial_and_journey_share_replay_journal(journey):
    world, starter, body = journey
    starter.start(body)
    replay = world.body(journey_version=1, operator_control_version=1, panel_id="operator")
    with pytest.raises(TrialError, match="navigation_trial_replay"):
        starter.start(replay)
    assert sum(row["action"] == "arm" for row in world.commands) == 1


def test_journey_http_contract_and_separate_starter(journey, monkeypatch):
    from flask import Flask

    from services.api_core import features_api, rider_routes
    from services.api_core.contract_registry import contract_for

    world, starter, body = journey
    monkeypatch.setattr(features_api, "feature_manager", world.manager)
    app = Flask(__name__)
    app.extensions["rider_navigation_journey"] = starter
    rider_routes.register_compute(app)
    result = app.test_client().post("/api/navigation/journey", json=body)
    assert result.status_code == 200
    assert result.json["status"]["journey"]["id"] == body["request_id"]
    assert contract_for("/api/navigation/journey").name == "rider.navigation_loop"


def test_command_boundary_keeps_journey_explicit_without_inferred_timed_lease():
    body = {
        "action": "arm",
        "source": "manual",
        "owner": "navigation",
        "arming_mode": "journey",
        "journey_version": 1,
        "journey_id": "mission",
        "operator_control_version": 1,
        "panel_id": "operator",
        "operator_consent": True,
        "operator_plan": "Isolated journey",
        "request_id": "start",
        "generation": "new",
        "seq": 0,
        "ts": time.time(),
        "ttl_ms": 500,
        "execution_context": "panel",
    }
    assert "lease_s" not in command_envelope(body)
    for invalid in ({"source": "navigation"}, {"lease_s": 100}, {"journey_version": True}, {"owner": "manual"}):
        with pytest.raises(ValueError, match="navigation_journey_invalid"):
            command_envelope({**body, **invalid})


def test_new_pi_with_old_host_fails_before_arm(journey, monkeypatch):
    from apps.compute import stream_prepare
    from apps.compute.client import ComputeError

    world, starter, body = journey

    def old_host(**kwargs):
        assert kwargs["journey_version"] == 1
        raise ComputeError("navigation_journey_update_required", 409)

    monkeypatch.setattr(stream_prepare, "prepare_stream", old_host)
    with pytest.raises(TrialError, match="navigation_journey_update_required"):
        starter.start(body)
    assert all(row["action"] != "arm" for row in world.commands)
