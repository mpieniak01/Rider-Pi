"""Pure presentation fixtures: no BUS, sockets, SDK or robot API imports."""

import time

import pytest

from services.api_core import navigation_state as cache


def test_no_default_map_or_fictional_origin_pose(monkeypatch):
    monkeypatch.setattr(cache, "_rows", {"map": None, "pose": None, "path": None})
    assert cache.snapshot() == {"map": None, "pose": None, "path": None}


def test_producer_timestamp_and_legitimate_zero_pose_are_preserved(monkeypatch):
    monkeypatch.setattr(cache, "_rows", {"map": None, "pose": None, "path": None})
    ts = time.time() - 4
    assert cache.observe("robot.pose", {"x": 0, "y": 0, "theta": 0, "ts": ts})
    row = cache.snapshot()["pose"]
    assert row["observed_at"] == ts
    assert row["x"] == 0
    assert row["stale"] is True
    assert cache.observe("robot.pose", {"x": 1, "y": 2, "theta": 0, "ts": ts - 1}) is False


def test_map_is_bounded_and_copied_without_replacing_source_time(monkeypatch):
    monkeypatch.setattr(cache, "_rows", {"map": None, "pose": None, "path": None})
    row = {"width_cells": 2, "height_cells": 2, "grid": [[0, 255], [127, 0]], "ts": time.time()}
    assert cache.observe("mapper.map.data", row)
    row["grid"][0][0] = 255
    value = cache.snapshot()["map"]
    assert value["grid"] == [0, 255, 127, 0]
    assert value["observed_at"] == row["ts"]
    value["grid"][0] = 127
    assert cache.snapshot()["map"]["grid"][0] == 0
    assert not cache.observe("mapper.map.data", dict(row, width_cells=100000))


def test_missing_time_and_invalid_measurement_do_not_become_fresh():
    assert not cache.observe("robot.pose", {"x": 0, "y": 0, "theta": 0})
    assert not cache.observe("robot.pose", {"x": None, "y": 0, "theta": 0, "ts": time.time()})
    assert not cache.observe("mapper.map.data", {"width_cells": 2, "height_cells": 2, "grid": [0], "ts": time.time()})
    assert not cache.observe("robot.pose", {"x": 0, "y": 0, "theta": 0, "ts": time.time() + 5})
    assert not cache.observe("robot.pose", {"x": 10**1000, "y": 0, "theta": 0, "ts": time.time()})
    assert not cache.observe("robot.pose", {"x": 0, "y": 0, "theta": 0, "ts": 10**1000})


def test_malformed_grid_and_nonfinite_values_are_rejected_without_raising():
    row = {"width_cells": 2, "height_cells": 2, "ts": time.time()}
    for grid in ([[0, 255], 0], [[0], [0, 0, 0]], [0, 0, 0, float("nan")]):
        assert not cache.observe("mapper.map.data", dict(row, grid=grid))


def test_path_is_normalized_and_nested_unbounded_fields_are_not_retained(monkeypatch):
    monkeypatch.setattr(cache, "_rows", {"map": None, "pose": None, "path": None})
    row = {"path": [{"x": 0, "y": 1, "unused": [1] * 10000}], "target": [2, 3], "ts": time.time()}
    assert cache.observe("navigator.path", row)
    assert cache.snapshot()["path"]["path"] == [[0, 1]]
    assert cache.snapshot()["path"]["target"] == [2, 3]
    assert not cache.observe("navigator.path", dict(row, target={"x": None, "y": 0}))


def test_explicit_quality_and_failure_flags_are_preserved(monkeypatch):
    monkeypatch.setattr(cache, "_rows", {"map": None, "pose": None, "path": None})
    for flags in (
        {"stale": True},
        {"offline": True},
        {"error": "sensor failed"},
        {"data_ready": False, "navigation_ready": False, "data_error": "uncalibrated"},
    ):
        assert cache.observe("robot.pose", {"x": 0, "y": 0, "theta": 0, "ts": time.time(), **flags})
        row = cache.snapshot()["pose"]
        assert all(row[key] == value for key, value in flags.items())
        if any(key in flags for key in ("stale", "offline", "error")):
            assert row["stale"] is True


def test_invalid_recognized_observation_expires_healthy_geometry(monkeypatch):
    monkeypatch.setattr(cache, "_rows", {"map": None, "pose": None, "path": None})
    ts = time.time()
    assert cache.observe("robot.pose", {"x": 0, "y": 0, "theta": 0, "ts": ts})
    assert not cache.observe("robot.pose", {"observed_at": None, "ts": ts, "error": "lost"})
    row = cache.snapshot()["pose"]
    assert row["stale"] is True
    assert row["observed_at"] is None
    assert row["error"] == "lost"
    assert "x" not in row
    assert not cache.observe("robot.pose", None)
    assert cache.snapshot()["pose"]["data_ready"] is False


def test_older_explicit_failure_expires_health_and_preserves_original_time(monkeypatch):
    monkeypatch.setattr(cache, "_rows", {"map": None, "pose": None, "path": None})
    ts = time.time()
    assert cache.observe("robot.pose", {"x": 0, "y": 0, "theta": 0, "observed_at": ts})
    assert not cache.observe("robot.pose", {"observed_at": ts - 1, "error": "sensor unavailable"})
    row = cache.snapshot()["pose"]
    assert row["observed_at"] == ts - 1
    assert row["stale"] is True
    assert row["error"] == "sensor unavailable"
    assert "x" not in row


def plan_fixture(monkeypatch):
    monkeypatch.setattr(cache, "_rows", {"map": None, "pose": None, "path": None})
    monkeypatch.setattr(cache.time, "time", lambda: 1000)
    home = {"x": 1, "y": 0, "calibration_id": "measured", "reference_id": "origin", "operator_confirmed": True}
    frame = {"calibration_id": "measured", "reference_id": "origin", "home": home}
    assert cache.observe(
        "robot.pose",
        {**frame, "x": 0, "y": 0, "theta": 0, "observed_at": 999.8, "data_ready": True, "navigation_ready": True},
    )
    assert cache.observe(
        "mapper.map.data",
        {
            **frame,
            "width_cells": 2,
            "height_cells": 1,
            "grid": [[0, 0]],
            "resolution_m": 1,
            "origin_x": 0,
            "origin_y": 0,
            "observed_at": 999.8,
            "data_ready": True,
            "planning_ready": True,
            "navigation_ready": False,
        },
    )
    return {
        "planning_only": True,
        "data_ready": True,
        "observed_at": 1000,
        "plan_observed_at": 999.8,
        "plan_calibration_id": "measured",
        "plan_reference_id": "origin",
        "plan_home": home,
        "planned_path": [[0, 0], [1, 0]],
        "planned_path_length": 2,
        "planned_path_truncated": False,
        "goal_pose": [1, 0],
        "data_error": "navigation_traversal_unverified",
    }


def test_passive_plan_heartbeat_does_not_refresh_source_age(monkeypatch):
    plan = plan_fixture(monkeypatch)
    assert cache.observe_plan(plan)["plan_observed_at"] == 999.8
    assert cache.snapshot()["path"]["observed_at"] == 999.8
    assert cache.snapshot()["path"]["navigation_ready"] is False
    monkeypatch.setattr(cache.time, "time", lambda: 1002)
    plan["observed_at"] = 1002
    cache.observe_plan(plan)
    assert cache.snapshot()["path"]["age_s"] == pytest.approx(2.2)
    assert cache.snapshot()["path"]["physical_completion"] == "unverified"


@pytest.mark.parametrize(
    "change",
    [
        {"plan_observed_at": None},
        {"plan_observed_at": 1001},
        {"observed_at": 999},
        {"planned_path": [[float("nan"), 0]]},
        {"planned_path": [[0, 0]] * 129},
        {"planned_path_length": True},
        {"planned_path_truncated": True},
        {"goal_pose": [0, 0]},
        {"plan_home": None},
        {"plan_reference_id": "other"},
        {"offline": True},
        {"error": "lost"},
        {"data_error": "camera_failed"},
        {"data_ready": False},
    ],
)
def test_corrupt_or_failed_passive_plan_expires_cached_geometry(monkeypatch, change):
    plan = plan_fixture(monkeypatch)
    cache.observe_plan(plan)
    result = cache.observe_plan({**plan, **change})
    assert result["planned_path"] == []
    assert result["plan_observed_at"] is None
    assert cache.snapshot()["path"]["stale"] is True
    assert "path" not in cache.snapshot()["path"]


def test_passive_plan_frame_change_hides_old_overlay_and_empty_plan_clears_it(monkeypatch):
    plan = plan_fixture(monkeypatch)
    cache.observe_plan(plan)
    frame = {"calibration_id": "measured", "reference_id": "new", "home": {**plan["plan_home"], "reference_id": "new"}}
    cache.observe("robot.pose", {**frame, "x": 0, "y": 0, "theta": 0, "observed_at": 1000})
    row = cache.snapshot()["path"]
    assert row["stale"] is True
    assert row["error"] == "plan_frame_mismatch"
    cache.observe_plan({**plan, "planned_path": [], "plan_observed_at": None})
    assert "path" not in cache.snapshot()["path"]


def test_older_passive_plan_cannot_replace_newer_plan_and_nested_fields_are_bounded(monkeypatch):
    plan = plan_fixture(monkeypatch)
    plan["plan_home"]["extra"] = [1] * 10000
    result = cache.observe_plan(plan)
    assert "extra" not in result["plan_home"]
    cache.observe_plan({**plan, "plan_observed_at": 999.7})
    assert cache.snapshot()["path"]["observed_at"] == 999.8


@pytest.mark.parametrize("source", ["map", "pose"])
@pytest.mark.parametrize(
    "change",
    [
        {"stale": True},
        {"offline": True},
        {"error": "lost"},
        {"data_ready": False},
        {"data_ready": None},
        {"data_error": "lost"},
        {"observed_at": 995},
        {"quality": "unknown"},
    ],
)
def test_same_frame_source_failure_cannot_present_a_current_plan(monkeypatch, source, change):
    plan = plan_fixture(monkeypatch)
    cache.observe_plan(plan)
    assert cache.snapshot()["path"]["planning_ready"] is True
    cache._rows[source].update(change)
    path = cache.snapshot()["path"]
    assert path["stale"] is True
    assert path["planning_ready"] is False
    assert path["error"] == "plan_sources_unavailable"


def test_same_frame_invalid_pose_has_no_current_passive_overlay(monkeypatch):
    plan = plan_fixture(monkeypatch)
    cache.observe_plan(plan)
    frame = {"calibration_id": "measured", "reference_id": "origin", "home": plan["plan_home"]}
    assert not cache.observe("robot.pose", {**frame, "observed_at": 1000, "error": "imu_failed"})
    assert cache.snapshot()["path"]["planning_ready"] is False
