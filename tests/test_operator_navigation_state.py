"""Pure presentation fixtures: no BUS, sockets, SDK or robot API imports."""

import time

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
    assert row["stale"] is True and row["observed_at"] is None and row["error"] == "lost"
    assert "x" not in row
    assert not cache.observe("robot.pose", None)
    assert cache.snapshot()["pose"]["data_ready"] is False


def test_older_explicit_failure_expires_health_and_preserves_original_time(monkeypatch):
    monkeypatch.setattr(cache, "_rows", {"map": None, "pose": None, "path": None})
    ts = time.time()
    assert cache.observe("robot.pose", {"x": 0, "y": 0, "theta": 0, "observed_at": ts})
    assert not cache.observe("robot.pose", {"observed_at": ts - 1, "error": "sensor unavailable"})
    row = cache.snapshot()["pose"]
    assert row["observed_at"] == ts - 1 and row["stale"] is True and row["error"] == "sensor unavailable"
    assert "x" not in row
