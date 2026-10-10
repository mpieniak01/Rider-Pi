"""Fictional verified geometry used only by isolated software fixtures."""


def fake_home(calibration="mock", reference="fake-origin", x=0, y=0):
    return {"x": x, "y": y, "operator_confirmed": True, "calibration_id": calibration, "reference_id": reference}


def fake_pose(observed, calibration="mock", reference="fake-origin", **fields):
    return {
        "x": 0,
        "y": 0,
        "theta": 0,
        "observed_at": observed,
        "navigation_ready": True,
        "planning_ready": True,
        "calibration_id": calibration,
        "reference_id": reference,
        "confidence": 0.8,
        "home": fake_home(calibration, reference),
        **fields,
    }


def fake_map(observed, calibration="mock", reference="fake-origin", **fields):
    return {
        "observed_at": observed,
        "data_ready": True,
        "planning_ready": True,
        "navigation_ready": False,
        "calibration_id": calibration,
        "reference_id": reference,
        "home": fake_home(calibration, reference),
        "range_calibration_id": "fictional-range",
        "stopping_horizon_verified": True,
        "stopping_horizon_m": 0.2,  # Fictional fixture, never a physical robot threshold.
        "range_quality": {"observed_at": observed, "ready": True},
        "width_cells": 3,
        "height_cells": 3,
        "resolution_m": 1,
        "origin_x": 0,
        "origin_y": 0,
        "grid": [[0, 0, 0], [0, 0, 0], [0, 0, 0]],
        **fields,
    }
