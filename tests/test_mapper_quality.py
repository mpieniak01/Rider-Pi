"""Range/map projection fixtures; all BUS and ranges are fake."""

from types import SimpleNamespace

import pytest
from quality_fakes import fake_home

from apps.mapper.main import CELL_UNKNOWN, Mapper, OccupancyGrid


@pytest.fixture
def mapper(monkeypatch):
    clock = SimpleNamespace(now=1000.0)
    sent = []
    monkeypatch.setattr("apps.mapper.main.BusSub", lambda *a: SimpleNamespace())
    monkeypatch.setattr("apps.mapper.main.BusPub", lambda: SimpleNamespace(publish=lambda *a, **kw: sent.append(a)))
    instance = Mapper(wall_clock=lambda: clock.now)
    instance._handle_robot_pose(
        {
            "x": 0,
            "y": 0,
            "theta": 0,
            "observed_at": clock.now,
            "navigation_ready": True,
            "reference_id": "fake-origin",
            "calibration_id": "mock",
            "home": fake_home(),
            "confidence": 0.8,
        }
    )
    return instance, clock, sent


def ranges(clock, **fields):
    return {
        "observed_at": clock.now,
        "range_verified": True,
        "reference_id": "fake-origin",
        "calibration_id": "mock",
        "footprint_verified": True,
        "footprint_radius_m": 0.1,
        "traversability_verified": True,
        "stopping_horizon_verified": True,
        "stopping_horizon_m": 0.2,  # Fictional fixture only.
        "obstacles": [{"angle": 0, "distance": 1}],
        **fields,
    }


@pytest.mark.parametrize(
    "fields",
    [
        {"observed_at": None},
        {"observed_at": 999},
        {"range_verified": False},
        {"calibration_id": None},
        {"footprint_verified": False},
        {"traversability_verified": False},
        {"stopping_horizon_verified": False},
        {"stopping_horizon_m": None},
        {"stopping_horizon_m": 0},
        {"footprint_radius_m": float("nan")},
        {"obstacles": []},
        {"obstacles": [{"distance": 1}]},
        {"obstacles": [{"distance": 1, "angle": float("nan")}]},
    ],
)
def test_unknown_range_cannot_modify_or_authorize_map(mapper, fields):
    instance, clock, _ = mapper
    instance._handle_obstacle_data(ranges(clock, **fields))
    assert instance.obstacles_processed == 0
    assert not instance.quality()["navigation_ready"]


def test_map_request_preserves_original_time_and_cells_expire(mapper):
    instance, clock, sent = mapper
    instance._handle_obstacle_data(ranges(clock))
    instance._handle_map_request({"request_id": "first"})
    first = sent[-1][1]
    assert first["observed_at"] == 1000 and first["request_id"] == "first"
    assert first["planning_ready"] and not first["navigation_ready"]
    clock.now += 4
    instance._handle_map_request({"request_id": "second"})
    second = sent[-1][1]
    assert second["observed_at"] is None and not second["navigation_ready"]
    assert all(cell == CELL_UNKNOWN for row in second["grid"] for cell in row)


def test_pose_and_range_order_errors_never_refresh_previous_map(mapper):
    instance, clock, _ = mapper
    instance._handle_obstacle_data(ranges(clock))
    instance._handle_obstacle_data(ranges(clock, observed_at=999.99))
    assert instance.data_error == "sample_out_of_order"
    assert not instance.quality()["navigation_ready"]


@pytest.mark.parametrize("dimensions", [(0, 1, 1), (1, 1, 0), (float("nan"), 1, 1), (1000, 1000, 0.01)])
def test_grid_allocation_bounded(dimensions):
    with pytest.raises(ValueError):
        OccupancyGrid(*dimensions)


@pytest.mark.parametrize("field", ["reference_id", "calibration_id"])
def test_new_coordinate_frame_clears_previous_cells_and_range(mapper, field):
    instance, clock, _ = mapper
    instance._handle_obstacle_data(ranges(clock))
    assert any(cell != CELL_UNKNOWN for row in instance.grid.snapshot(clock.now) for cell in row)
    replacement = dict(instance.pose_sample, **{field: "new-frame"})
    replacement["home"] = dict(replacement["home"], **{field: "new-frame"})
    instance._handle_robot_pose(replacement)
    assert not instance.quality()["navigation_ready"] and instance.range_sample is None
    assert all(cell == CELL_UNKNOWN for row in instance.grid.snapshot(clock.now) for cell in row)
    instance._handle_obstacle_data(ranges(clock))
    assert instance.quality()["planning_ready"] and instance.quality()[field] == "new-frame"


def test_expired_cells_are_unknown_in_operator_statistics(mapper):
    instance, clock, _ = mapper
    instance._handle_obstacle_data(ranges(clock))
    clock.now += 4
    assert instance.grid.get_occupancy_info(clock.now)["explored_percent"] == 0


def test_negative_lower_map_boundary_never_truncates_into_free_border():
    grid = OccupancyGrid(1, 1, 0.05)
    assert grid.world_to_grid(-0.501, -0.501) == (-1, -1)
    with pytest.raises(ValueError):
        OccupancyGrid(1e308, 1e308, 1e-308)
