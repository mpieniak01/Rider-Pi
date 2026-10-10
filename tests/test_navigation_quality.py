"""Autonomy regression fixtures: no hardware, real sockets, or physical robot."""

from types import SimpleNamespace

import pytest
from quality_fakes import fake_home, fake_map, fake_pose

from apps.navigator.main import Navigator, NavigatorState, Strategy
from apps.navigator.path_control import checked_grid
from apps.navigator.pathfinding import find_path, world_to_grid


@pytest.fixture
def navigator(monkeypatch):
    clock = SimpleNamespace(now=1000.0)
    state = {"can_move": True, "owner": "navigation", "generation": "mock-gen", "last_seq": -1}
    monkeypatch.setattr("services.safety_contract.read_status", lambda: dict(state))
    sent = []
    monkeypatch.setattr(
        "apps.navigator.main.BusPub", lambda **kw: SimpleNamespace(publish=lambda *a, **kw: sent.append(a))
    )
    monkeypatch.setattr("apps.navigator.main.BusSub", lambda *a, **kw: SimpleNamespace(close=lambda: None))
    nav = Navigator(wall_clock=lambda: clock.now, clock=lambda: clock.now)
    nav._motion_generation = nav._request_generation = "mock-gen"
    nav._intent_start_ts = clock.now
    nav._request_id = "mock-click"
    nav.pose_sample = fake_pose(clock.now)
    nav.current_pose = (0, 0, 0)
    nav.map_sample = fake_map(clock.now)
    return nav, clock, state, sent


def clear(clock, **fields):
    return {"observed_at": clock.now, "present": False, "confidence": 0.8, "data_ready": True, **fields}


def commands(sent, action):
    return [row for topic, row in sent if topic == "motion.command" and row.get("action") == action]


def start_verified_return(nav, clock):
    """An old sent goal is simulated as state; this helper never emits MOVE."""
    nav.state = NavigatorState.RETURNING_HOME
    nav.goal_pose = (1, 0)
    nav.current_path = [(1, 0)]
    nav.pose_sample["home"]["x"] = nav.map_sample["home"]["x"] = 1
    nav.obstacle_sample = clear(clock)
    nav._motion_started = True


def test_start_without_observation_waits_without_actuation(navigator):
    nav, _, _, sent = navigator
    nav.start()
    assert nav.active and not commands(sent, "move")
    assert not nav.navigation_quality()["navigation_ready"]


@pytest.mark.parametrize(
    "fields",
    [
        {"observed_at": None},
        {"observed_at": 999},
        {"observed_at": 1001},
        {"error": "camera_missing"},
        {"stale": True},
        {"offline": True},
        {"present": None},
        {"confidence": float("nan")},
        {"confidence": 0},
        {"data_ready": False},
    ],
)
def test_failed_source_during_motion_stops_and_cannot_auto_resume(navigator, fields):
    nav, clock, _, sent = navigator
    start_verified_return(nav, clock)
    assert nav._motion_started and not commands(sent, "move")
    nav._handle_obstacle_sample(clear(clock, **fields))
    assert commands(sent, "stop") and not nav.active
    assert nav._motion_generation is None
    before = len(commands(sent, "move"))
    clock.now += 0.05
    nav._handle_obstacle_sample(clear(clock))
    assert len(commands(sent, "move")) == before
    assert not nav.navigation_quality()["navigation_ready"]


def test_autonomous_zero_cannot_bypass_unverified_traversal(navigator):
    nav, clock, _, sent = navigator
    start_verified_return(nav, clock)
    nav._send_motion_drive(0, 0)
    assert not commands(sent, "move") and commands(sent, "stop")
    clock.now += 0.6
    nav._quality_tick()
    assert commands(sent, "stop") and not nav.active


def test_mode_change_invalidates_original_source(navigator):
    nav, clock, _, sent = navigator
    start_verified_return(nav, clock)
    nav._handle_ai_mode_change({"mode": "pc_offload"})
    assert nav.obstacle_sample is None and commands(sent, "stop")


def test_observation_before_intent_cannot_start_motion(navigator):
    nav, clock, _, sent = navigator
    nav.obstacle_sample = clear(clock, observed_at=999.9)
    nav.start()
    assert not commands(sent, "move")
    assert nav.data_error == "observation_before_intent"


def test_active_avoid_cannot_turn_into_unobserved_side_space(navigator):
    nav, clock, _, sent = navigator
    nav.strategy = Strategy.AVOID
    nav.start()
    nav._handle_obstacle_sample(clear(clock))
    nav._handle_obstacle_sample(clear(clock, present=True))
    assert commands(sent, "stop")
    assert all(row["yaw"] == 0 for row in commands(sent, "move"))


@pytest.mark.parametrize(
    "fields",
    [
        {"navigation_ready": False},
        {"calibration_id": None},
        {"x": float("nan")},
        {"observed_at": None},
        {"confidence": 0},
    ],
)
def test_invalid_pose_during_return_home_is_canonical_stop(navigator, fields):
    nav, clock, _, sent = navigator
    nav.state = NavigatorState.RETURNING_HOME
    nav._handle_robot_pose(
        {
            "x": 0,
            "y": 0,
            "theta": 0,
            "navigation_ready": True,
            "reference_id": "fake-origin",
            "calibration_id": "mock-record",
            "home": fake_home("mock-record"),
            "confidence": 0.8,
            "observed_at": clock.now,
            **fields,
        }
    )
    assert nav.current_pose is None and commands(sent, "stop")
    assert nav.state == NavigatorState.PATH_BLOCKED


def test_positive_ccw_heading_does_not_enable_unverified_autonomous_turn(navigator):
    nav, clock, _, sent = navigator
    nav.state = NavigatorState.RETURNING_HOME
    nav.obstacle_sample = clear(clock)
    nav.map_sample = fake_map(clock.now, "mock-record")
    nav._handle_robot_pose(
        {
            "x": 0,
            "y": 0,
            "theta": 0,
            "navigation_ready": True,
            "reference_id": "fake-origin",
            "calibration_id": "mock-record",
            "home": fake_home("mock-record"),
            "confidence": 0.8,
            "observed_at": clock.now,
        }
    )
    nav.goal_pose = (0, 1)
    nav.current_path = [(0, 1)]
    nav._update_path_following()
    assert not commands(sent, "move") and commands(sent, "stop")


@pytest.mark.parametrize(
    "fields",
    [
        {"planning_ready": False},
        {"width_cells": 0},
        {"width_cells": True},
        {"width_cells": 65537},
        {"grid": [[None]]},
        {"grid": []},
        {"resolution_m": 0},
        {"origin_x": float("nan")},
    ],
)
def test_map_schema_is_bounded_and_explicit(fields):
    row = fake_map(1000, width_cells=1, height_cells=1, grid=[[0]])
    row.update(fields)
    with pytest.raises(ValueError):
        checked_grid(row)


def test_unknown_or_diagonal_corner_never_becomes_traversable():
    row = {
        "width_cells": 2,
        "height_cells": 2,
        "resolution_m": 1,
        "origin_x": 0,
        "origin_y": 0,
        "grid": [[0, 127], [255, 0]],
    }
    assert find_path(row, (0, 0), (1, 1), allow_unknown=False) is None


@pytest.mark.parametrize("field", ["reference_id", "calibration_id"])
def test_returning_home_frame_change_stops_existing_path(navigator, field):
    nav, clock, _, sent = navigator
    nav.state = NavigatorState.RETURNING_HOME
    pose = {
        "x": 0,
        "y": 0,
        "theta": 0,
        "observed_at": clock.now,
        "navigation_ready": True,
        "calibration_id": "mock",
        "reference_id": "origin",
        "home": fake_home("mock", "origin"),
    }
    nav._return_frame = ("mock", "origin")
    nav.map_sample = dict(pose)
    replacement = dict(pose, **{field: "other"})
    replacement["home"] = dict(pose["home"], **{field: "other"})
    nav._handle_robot_pose(replacement)
    assert nav.current_pose is None and commands(sent, "stop")
    assert nav.state == NavigatorState.PATH_BLOCKED


def test_matching_request_map_from_different_frame_is_rejected(navigator):
    nav, clock, _, sent = navigator
    nav.state = NavigatorState.RETURNING_HOME
    nav.waiting_for_map = True
    nav._map_request_id = "return"
    nav.current_pose = (0, 0, 0)
    nav.pose_sample = {
        "x": 0,
        "y": 0,
        "theta": 0,
        "observed_at": clock.now,
        "navigation_ready": True,
        "calibration_id": "mock",
        "reference_id": "current",
        "home": fake_home("mock", "current"),
    }
    nav._handle_map_data(
        {
            "observed_at": clock.now,
            "navigation_ready": True,
            "planning_ready": True,
            "request_id": "return",
            "calibration_id": "mock",
            "reference_id": "old",
            "home": fake_home("mock", "old"),
            "stopping_horizon_verified": True,
            "stopping_horizon_m": 0.2,
            "width_cells": 1,
            "height_cells": 1,
            "resolution_m": 1,
            "origin_x": 0,
            "origin_y": 0,
            "grid": [[0]],
        }
    )
    assert commands(sent, "stop") and nav.data_error == "map_pose_frame_mismatch"


def test_new_operator_request_does_not_hide_prior_motion_history(navigator, monkeypatch):
    nav, clock, _, sent = navigator
    start_verified_return(nav, clock)
    envelope = {
        "generation": "mock-gen",
        "seq": 10,
        "request_id": "new-click",
        "ts": clock.now,
    }
    monkeypatch.setattr("apps.navigator.safety.authorize_request", lambda row: (envelope, {}))
    assert nav._accept_motion_request(envelope) and nav._motion_started
    nav._handle_obstacle_sample(clear(clock, error="camera_failed"))
    assert commands(sent, "stop")


def test_pathfinding_negative_boundary_is_outside_grid():
    assert world_to_grid(-0.001, -0.001, 0.05, 0, 0) == (-1, -1)


@pytest.mark.parametrize("grid", [[[127]], [[255]], [[0]]])
def test_exploration_clear_roi_never_proves_a_physical_corridor(navigator, grid):
    nav, clock, _, sent = navigator
    nav.map_sample = fake_map(clock.now, width_cells=1, height_cells=1, grid=grid)
    nav.start()
    nav._handle_obstacle_sample(clear(clock))
    assert not commands(sent, "move") and commands(sent, "stop")
    assert not nav.navigation_quality()["navigation_ready"]
    assert nav.data_error == "navigation_traversal_unverified"


@pytest.mark.parametrize("field", ["home", "range_quality", "stopping_horizon_verified"])
def test_loss_of_verified_return_geometry_revokes_motion(navigator, field):
    nav, clock, _, sent = navigator
    start_verified_return(nav, clock)
    assert nav._motion_started and not commands(sent, "move")
    nav.map_sample[field] = None
    nav._quality_tick()
    assert commands(sent, "stop") and nav._motion_generation is None
    assert not nav.navigation_quality()["navigation_ready"]


def test_return_goal_uses_explicit_home_instead_of_zero(navigator, monkeypatch):
    nav, clock, _, sent = navigator
    nav.obstacle_sample = clear(clock)
    nav.pose_sample["home"] = fake_home(x=2, y=3)
    envelope = {"generation": "mock-gen", "seq": 10, "request_id": "home-click", "ts": clock.now}
    monkeypatch.setattr("apps.navigator.safety.authorize_request", lambda row: (envelope, {}))
    nav._handle_return_home_start(envelope)
    assert nav.goal_pose == (2, 3) and nav.waiting_for_map
    assert not commands(sent, "move") and commands(sent, "stop")


def test_valid_map_schema_still_does_not_claim_physical_completion():
    assert checked_grid(fake_map(1000))["grid"][0][0] == 0


def test_verified_point_plan_is_inspectable_and_never_actuates(navigator):
    nav, clock, _, sent = navigator
    nav.state = NavigatorState.RETURNING_HOME
    nav.goal_pose = (1, 0)
    nav.waiting_for_map = True
    nav._map_request_id = "passive-plan"
    nav.obstacle_sample = clear(clock)
    nav.pose_sample["home"]["x"] = 1
    row = fake_map(clock.now, request_id="passive-plan")
    row["home"]["x"] = 1
    nav._handle_map_data(row)
    assert nav.current_path and nav.state == NavigatorState.PATH_BLOCKED
    assert not nav.navigation_quality()["navigation_ready"]
    assert nav.data_error == "navigation_traversal_unverified" and not commands(sent, "move")
    nav._publish_state(force=True)
    state = next(row for topic, row in reversed(sent) if topic == "navigator.state")
    assert state["planned_path"] and state["planning_only"]
    assert state["plan_observed_at"] == clock.now
    clock.now += 1
    nav._publish_state(force=True)
    heartbeat = next(row for topic, row in reversed(sent) if topic == "navigator.state")
    assert heartbeat["observed_at"] == clock.now
    assert heartbeat["plan_observed_at"] == clock.now - 1


@pytest.mark.parametrize("field", ["reference_id", "calibration_id", "home", "error"])
def test_cached_passive_plan_is_invalidated_by_changed_reference_or_failed_pose(navigator, field):
    nav, clock, _, sent = navigator
    nav.state = NavigatorState.RETURNING_HOME
    nav.goal_pose = (1, 0)
    nav._map_request_id = "passive-plan"
    nav.pose_sample["home"]["x"] = 1
    row = fake_map(clock.now, request_id="passive-plan")
    row["home"]["x"] = 1
    nav._handle_map_data(row)
    assert nav.current_path
    replacement = fake_pose(clock.now + 0.1)
    replacement["home"]["x"] = 1
    if field in {"reference_id", "calibration_id"}:
        replacement[field] = replacement["home"][field] = "new-frame"
    elif field == "home":
        replacement["home"]["x"] = 2
    else:
        replacement["error"] = "imu_failed"
    clock.now += 0.1
    nav._handle_robot_pose(replacement)
    assert not nav.current_path and nav.goal_pose is None
    assert nav.plan_observed_at is None and nav.plan_frame is None
    assert not commands(sent, "move")


def test_passive_map_reply_survives_its_own_stop_lease_revocation(navigator, monkeypatch):
    nav, clock, state, sent = navigator
    nav.obstacle_sample = clear(clock)
    nav.pose_sample["home"]["x"] = 1
    envelope = {"generation": "mock-gen", "seq": 10, "request_id": "home-click", "ts": clock.now}
    monkeypatch.setattr("apps.navigator.safety.authorize_request", lambda row: (envelope, {}))
    nav._handle_return_home_start(envelope)
    state.update(can_move=False, generation="after-stop")
    nav._consume_task_intent()
    assert nav.state == NavigatorState.RETURNING_HOME and nav._motion_generation is None
    row = fake_map(clock.now, request_id=nav._map_request_id)
    row["home"]["x"] = 1
    nav._handle_map_data(row)
    assert nav.current_path and nav.state == NavigatorState.PATH_BLOCKED
    assert not commands(sent, "move")


def test_explicit_stop_removes_cached_passive_plan(navigator):
    nav, clock, _, sent = navigator
    nav.state = NavigatorState.RETURNING_HOME
    nav.goal_pose = (1, 0)
    nav._map_request_id = "passive-plan"
    nav.pose_sample["home"]["x"] = 1
    row = fake_map(clock.now, request_id="passive-plan")
    row["home"]["x"] = 1
    nav._handle_map_data(row)
    assert nav.current_path and not nav.active
    nav.stop()
    assert not nav.current_path and nav.goal_pose is None and nav.plan_frame is None
    assert nav.state == NavigatorState.STOPPED and not commands(sent, "move")


def test_pending_home_plan_refuses_changed_home_with_same_frame(navigator):
    nav, clock, _, sent = navigator
    nav.state = NavigatorState.RETURNING_HOME
    nav.goal_pose = (1, 0)
    nav._return_frame = ("mock-record", "fake-origin")
    pose = fake_pose(clock.now)
    pose["home"]["x"] = 2
    nav._handle_robot_pose(pose)
    assert nav.state == NavigatorState.PATH_BLOCKED and nav.goal_pose is None
    assert not commands(sent, "move")
