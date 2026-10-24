"""Pi-owned visual measurement references; never an actuator or model policy."""

from __future__ import annotations

import copy
import math
import os
from pathlib import Path

from services.compute_config import _lock, _write

FIELDS = {
    "visible",
    "frame_size",
    "track_width_cm",
    "robot_width_cm",
    "camera_height_cm",
    "left_edge",
    "right_edge",
    "markers",
    "reference_pose",
}


def path():
    return Path(os.getenv("RIDER_IMAGE_REFERENCE", "data/navigation_image_reference.json"))


def number(value, low, high):
    return type(value) in (int, float) and low <= value <= high and math.isfinite(value)


def valid_point(point):
    return isinstance(point, list) and len(point) == 2 and all(number(v, 0, 1) for v in point)


def valid_edge(edge):
    return (
        isinstance(edge, list)
        and len(edge) == 2
        and all(valid_point(point) for point in edge)
        and edge[0][1] < edge[1][1]
    )


def valid_edges(left, right):
    return all(valid_edge(edge) for edge in (left, right)) and all(
        abs(a[1] - b[1]) <= 1e-6 and b[0] - a[0] >= 0.01 for a, b in zip(left, right)
    )


def valid_markers(marks):
    return (
        isinstance(marks, list)
        and 2 <= len(marks) <= 8
        and all(
            isinstance(point, list) and len(point) == 2 and number(point[0], 0.1, 1000) and number(point[1], 0, 1)
            for point in marks
        )
        and all(a[0] < b[0] and a[1] > b[1] for a, b in zip(marks, marks[1:]))
    )


def validate(values):
    invalid = ValueError("image_reference_invalid")
    if not isinstance(values, dict) or set(values) != FIELDS:
        raise invalid
    if type(values["visible"]) is not bool or values["reference_pose"] != "lowest":
        raise invalid
    size = values["frame_size"]
    if (
        not isinstance(size, list)
        or len(size) != 2
        or any(type(v) is not int for v in size)
        or not 32 <= size[0] <= 1280
        or not 32 <= size[1] <= 720
    ):
        raise invalid
    for key in ("track_width_cm", "robot_width_cm", "camera_height_cm"):
        if not number(values[key], 0.1, 1000):
            raise invalid
    if values["robot_width_cm"] > values["track_width_cm"]:
        raise invalid
    if not valid_edges(values["left_edge"], values["right_edge"]):
        raise invalid
    if not valid_markers(values["markers"]):
        raise invalid
    return copy.deepcopy(values)


def snapshot():
    target = path()
    if not target.exists():
        return {"version": 1, "revision": 0, "values": None, "purpose": "visual_reference_only"}
    import json

    if target.stat().st_size > 8192:
        raise ValueError("image_reference_invalid")
    state = json.loads(target.read_text())
    if (
        not isinstance(state, dict)
        or set(state) != {"version", "revision", "values", "purpose"}
        or type(state["version"]) is not int
        or state["version"] != 1
        or type(state["revision"]) is not int
        or state["revision"] < 0
        or state["purpose"] != "visual_reference_only"
    ):
        raise ValueError("image_reference_invalid")
    state["values"] = validate(state["values"])
    return state


def configure(body):
    if (
        not isinstance(body, dict)
        or set(body) != {"revision", "values"}
        or type(body["revision"]) is not int
        or body["revision"] < 0
    ):
        raise ValueError("image_reference_invalid")
    values = validate(body["values"])
    with _lock(path()):
        state = snapshot()
        if body["revision"] != state["revision"]:
            raise ValueError("image_reference_conflict")
        state.update(revision=state["revision"] + 1, values=values)
        _write(path(), state)
        return state
