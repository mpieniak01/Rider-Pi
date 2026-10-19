"""Navigation characterization uses fictional geometry, fake services and memory BUS."""

import copy
from types import SimpleNamespace

import pytest
from quality_fakes import fake_map
from test_mapper_quality import mapper as mapper, ranges
from test_navigation_quality import clear, commands, navigator as navigator
from test_navigation_trial import world as world

from apps.choreographer.main import _subscription_topics
from apps.navigator import motion
from apps.navigator.main import NavigatorState
from apps.navigator.path_control import checked_grid
from apps.navigator.pathfinding import find_path_grid
from services import navigation_config
from services.navigation_trial import TrialError, public_status, validate_request
from services.navigation_trial_preparation import TrialPreparation


@pytest.mark.parametrize(
    "edits,error",
    [
        ({"range_verified": False, "footprint_verified": False}, "range_manual_characterization_required"),
        ({"footprint_verified": False, "obstacles": []}, "footprint_range_and_stopping_horizon_unverified"),
        ({"obstacles": []}, "range_geometry_unknown"),
        ({"obstacles": [{"angle": False, "distance": 1}]}, "invalid_range_geometry"),
    ],
)
def test_mapper_rejection_precedence_keeps_cells_and_timestamps(mapper, edits, error):
    instance, clock, _ = mapper
    before = instance.grid.grid.copy(), instance.grid.observed.copy(), instance.last_range_ts
    instance._handle_obstacle_data(ranges(clock, **edits))
    assert instance.data_error == error
    assert (instance.grid.grid == before[0]).all()
    assert (instance.grid.observed == before[1]).all()
    assert instance.last_range_ts == before[2]
    assert instance.obstacles_processed == 0


def test_mapper_valid_range_marks_ray_before_obstacle(mapper, monkeypatch):
    instance, clock, _ = mapper
    events = []
    monkeypatch.setattr(instance.grid, "mark_ray", lambda *a: events.append(("ray", a)))
    monkeypatch.setattr(instance.grid, "mark_obstacle", lambda *a, **kw: events.append(("obstacle", a, kw)))
    instance._handle_obstacle_data(ranges(clock))
    assert [e[0] for e in events] == ["ray", "obstacle"]
    assert events[0][1] == (0, 0, 1.0, 0.0)
    assert events[1][2] == {"inflation_radius": 0.1}
    assert instance.grid.observation_time == clock.now
    assert instance.obstacles_processed == 1


@pytest.mark.parametrize(
    "edits,error",
    [
        ({"planning_ready": False, "width_cells": -1}, "map_unverified"),
        ({"width_cells": -1, "grid": []}, "map_dimensions_invalid"),
        ({"grid": [[False] * 3] * 3}, "map_cell_invalid"),
        ({"grid": [[]]}, "map_grid_invalid"),
    ],
)
def test_grid_checks_preserve_geometry_before_cell_validation(edits, error):
    row = fake_map(1000, **edits)
    before = copy.deepcopy(row)
    with pytest.raises(ValueError, match=error):
        checked_grid(row)
    assert row == before


def test_pathfinding_rejects_diagonal_corner_and_stays_deterministic():
    assert find_path_grid([[0, 255], [255, 0]], 0, 0, 1, 1, 2, 2, False) is None
    first = find_path_grid([[0] * 3 for _ in range(3)], 0, 0, 2, 2, 3, 3, False)
    assert first == [(0, 0), (2, 2)]
    assert find_path_grid([[127, 0]], 0, 0, 1, 0, 2, 1, False) is None


def test_navigator_failed_intent_claim_never_starts(navigator, monkeypatch):
    nav, clock, _, sent = navigator
    from apps.safety import state

    monkeypatch.setattr(
        state, "read_status", lambda: {"can_move": True, "owner": "navigation", "generation": "mock-gen"}
    )
    intent = {"generation": "mock-gen", "request_id": "new", "seq": 5, "ts": clock.now}
    monkeypatch.setattr(motion, "read_service_intent", lambda *_: intent)
    monkeypatch.setattr(motion, "write_intent_status", lambda *a, **kw: False)
    monkeypatch.setattr(nav, "start", lambda: pytest.fail("unclaimed intent started"))
    nav._consume_task_intent()
    assert nav.state == NavigatorState.STOPPED
    assert nav.active is False
    assert nav._consumed_intent is None
    assert not commands(sent, 'move')


def test_navigator_config_validation_is_atomic_and_requires_disarmed(navigator, monkeypatch):
    nav, _, _, _ = navigator
    from apps.safety import state

    monkeypatch.setattr(state, "read_status", lambda: {"state": "DISARMED"})
    before = nav.fwd_speed, nav.turn_speed, nav.strategy
    nav._handle_control_command({"action": "config", "config": {"fwd_speed": 0.1, "turn_speed": True}})
    assert (nav.fwd_speed, nav.turn_speed, nav.strategy) == before
    monkeypatch.setattr(state, "read_status", lambda: {"state": "ARMED"})
    nav._handle_control_command({"action": "config", "config": {"fwd_speed": 0.1}})
    assert (nav.fwd_speed, nav.turn_speed, nav.strategy) == before


def test_navigator_invalid_pose_clears_plan_without_adopting_new_frame(navigator):
    nav, _, _, sent = navigator
    nav.current_path = [(0, 0), (1, 1)]
    nav.state = NavigatorState.RETURNING_HOME
    nav._handle_robot_pose({"x": False, "observed_at": 999})
    assert nav.current_path == []
    assert nav.current_pose is None
    assert nav.pose_sample is None
    assert nav.state == NavigatorState.PATH_BLOCKED
    assert not commands(sent, "move")


def test_navigator_quality_precedence_remains_passive(navigator):
    nav, clock, _, sent = navigator
    nav.obstacle_sample = clear(clock, present=True)
    nav.map_sample["stopping_horizon_verified"] = False
    assert nav.navigation_quality()["data_error"] == "obstacle_present"
    nav._data_blocked, nav.data_error = True, "sticky_failure"
    assert nav.navigation_quality()["data_error"] == "sticky_failure"
    nav._data_blocked = False
    nav.obstacle_sample = clear(clock)
    assert nav.navigation_quality()["data_error"] == "map_stopping_horizon_unverified"
    assert not nav.navigation_quality()['navigation_ready']
    assert not commands(sent, 'move')


@pytest.mark.parametrize(
    "edits,error",
    [
        ({"speed": 2, "corridor": []}, "navigation_speed_invalid"),
        ({"corridor": [], "perception": {}}, "navigation_corridor_invalid"),
        ({"perception": {}, "avoidance": {}}, "navigation_perception_invalid"),
        ({"avoidance": {}}, "navigation_avoidance_invalid"),
    ],
)
def test_policy_rejection_order_does_not_modify_input(edits, error):
    row = copy.deepcopy(navigation_config.DEFAULT)
    row.update(edits)
    before = copy.deepcopy(row)
    with pytest.raises(ValueError, match=error):
        navigation_config.validate(row)
    assert row == before


def test_trial_operator_metadata_precedes_consent_and_age(world):
    payload = world.body(panel_id="", operator_control_version=True, operator_consent=False, ts=0)
    with pytest.raises(TrialError, match="operator_control_invalid"):
        validate_request(payload, world.trial.wall())
    assert world.actions == world.commands == []


def test_trial_request_rejection_precedes_service_change_and_reservation(world):
    before = world.gate.generation, world.gate.last_seq
    with pytest.raises(TrialError, match="manual_settings_stale"):
        world.trial.start(world.body(settings_revision=4))
    assert world.actions == world.commands == []
    assert (world.gate.generation, world.gate.last_seq) == before
    assert not world.manager._state_path.with_name("navigation_trial_requests.json").exists()


def test_trial_source_reservation_precedes_old_producer_stop_and_arm(world, monkeypatch):
    from apps.compute import stream_prepare

    events = []
    original = world.manager.set_feature

    def set_feature(name, enabled, **kwargs):
        events.append((name, enabled))
        return original(name, enabled, **kwargs)

    monkeypatch.setattr(world.manager, "set_feature", set_feature)
    monkeypatch.setattr(stream_prepare, "prepare_stream", lambda **kw: events.append(("stream", kw)))
    assert world.trial.start(world.body())["ok"]
    assert events[:3] == [("s2_camera_preview", True), ("s14_venom_navigation", False), ("s15_venom_perception", False)]
    assert events[3][0] == 'stream'
    assert events[4] == ('s14_venom_navigation', True)
    assert not any(c["action"] == "move" for c in world.commands)


def test_trial_cleanup_failure_cannot_skip_scoped_stop(world, monkeypatch):
    payload = world.body()
    prep = TrialPreparation(world.trial, payload, world.safety(), world.elapsed)
    prep.context.update(armed=True, arm_generation=world.gate.generation)
    events = []

    def fail_service(*_args, **_kwargs):
        events.append("service")
        raise OSError("fake service failure")

    monkeypatch.setattr(world.manager, "set_feature", fail_service)
    monkeypatch.setattr(prep, "stop_old", lambda owner: events.append(("stop", owner)))
    prep._cleanup_armed()
    assert events == ["service", ("stop", "navigation")]


def test_trial_cleanup_never_stops_new_generation(world, monkeypatch):
    prep = TrialPreparation(world.trial, world.body(), world.safety(), world.elapsed)
    prep.context.update(armed=True, arm_generation="old-generation")
    monkeypatch.setattr(world.manager, "set_feature", lambda *_: {"ok": True})
    monkeypatch.setattr(prep, "stop_old", lambda *_: pytest.fail("cleanup stopped a new generation"))
    prep._cleanup_armed()
    assert world.commands == []


def test_public_status_expiry_preserves_input_and_hides_monotonic():
    row = {
        "mode": "drive",
        "running": True,
        "sampled_monotonic": 10,
        "run_started_monotonic": 9,
        "permit_remaining_ms": 50,
        "feedback_remaining_ms": 150,
        "response_age_ms": 20,
        "decision": {"action": "go"},
    }
    before = copy.deepcopy(row)
    result = public_status(row, sampled_now=10.1)
    assert row == before
    assert result['permit_remaining_ms'] == 0
    assert result['feedback_remaining_ms'] == 50
    assert result['waiting_feedback']
    assert result['paused']
    assert result["decision"]["action"] == "stop"
    assert result["decision_age_ms"] == 120
    assert 'sampled_monotonic' not in result
    assert 'run_started_monotonic' not in result


def test_choreographer_topic_collection_preserves_wildcard_and_idle_fallback():
    assert _subscription_topics([]) == {"events"}
    assert _subscription_topics([{"trigger": {"topic": "vision.*"}}, {"trigger": {"topic": "vision.clear"}}, {}]) == {
        "vision",
        "vision.clear",
    }
