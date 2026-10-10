"""Bounded presentation cache; read-only snapshots never start navigation."""

from __future__ import annotations

import copy
import math
import threading
import time

from common.data_quality import confirmed_home, frame_identity, pose_status, sample_status

TOPICS = {"mapper.map.data": "map", "robot.pose": "pose", "navigator.path": "path"}
MAX_CELLS = 65536
MAX_PATH = 2000
_lock = threading.Lock()
_rows: dict[str, dict | None] = {"map": None, "pose": None, "path": None}


def _finite(value: object) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _point(value: object) -> list[float] | None:
    if isinstance(value, dict):
        coords = [value.get("x"), value.get("y")]
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        coords = list(value)
    else:
        return None
    return coords if all(_finite(item) for item in coords) else None


def _metadata(data: dict, topic: str, ts: float | None) -> dict:
    row = {"observed_at": ts, "source": topic}
    for key in ("stale", "offline", "data_ready", "navigation_ready", "planning_ready", "planning_only"):
        if type(data.get(key)) is bool:
            row[key] = data[key]
    for key in ("error", "data_error", "calibration_id", "reference_id", "physical_completion"):
        if isinstance(data.get(key), str):
            row[key] = data[key][:512]
    if confirmed_home(data) is not None and all(
        len(data["home"][key]) <= 512 for key in ("calibration_id", "reference_id")
    ):
        row["home"] = {
            key: data["home"][key] for key in ("x", "y", "calibration_id", "reference_id", "operator_confirmed")
        }
    if type(data.get("path_length")) is int and 0 <= data["path_length"] <= MAX_CELLS:
        row["path_length"] = data["path_length"]
    if type(data.get("path_truncated")) is bool:
        row["path_truncated"] = data["path_truncated"]
    if isinstance(data.get("quality"), str):
        row["quality"] = data["quality"][:128]
    elif "quality" in data and data["quality"] is None:
        row["quality"] = None
    elif _finite(data.get("quality")):
        row["quality"] = data["quality"]
    return row


def _store(name: str, row: dict) -> bool:
    quality = row.get("quality")
    healthy = (
        row.get("stale") is not True
        and row.get("offline") is not True
        and not row.get("error")
        and not row.get("data_error")
        and row.get("data_ready") is not False
        and row.get("navigation_ready") is not False
        and not ("quality" in row and quality is None)
        and not (
            isinstance(quality, str) and quality.lower() in {"unknown", "unavailable", "invalid", "error", "failed"}
        )
    )
    passive = (
        row.get("planning_only") is True
        and row.get("planning_ready") is True
        and row.get("stale") is not True
        and row.get("offline") is not True
        and not row.get("error")
        and row.get("data_error") == "navigation_traversal_unverified"
    )
    with _lock:
        previous = _rows[name]
        if previous is not None and _finite(previous.get("observed_at")) and _finite(row.get("observed_at")):
            if previous["observed_at"] > row["observed_at"] and (healthy or passive):
                return False
        _rows[name] = row
    return True


def _invalidate(name: str, topic: str, data: object, ts: float | None = None) -> bool:
    row = _metadata(data if isinstance(data, dict) else {}, topic, ts)
    row.update(stale=True, data_ready=False)
    row.setdefault("error", "invalid_navigation_data")
    _store(name, row)
    return False


def observe(topic: str, data: object) -> bool:
    """Retain original producer time and only bounded JSON presentation data."""
    name = TOPICS.get(topic)
    if name is None:
        return False
    if not isinstance(data, dict):
        return _invalidate(name, topic, data)
    ts = data.get("observed_at", data.get("ts"))
    if not _finite(ts) or ts <= 0 or ts > time.time() + 0.1:
        return _invalidate(name, topic, data)
    row = dict(data, observed_at=ts)
    if name == "map":
        width, height = row.get("width_cells"), row.get("height_cells")
        if (
            isinstance(width, bool)
            or isinstance(height, bool)
            or not isinstance(width, int)
            or not isinstance(height, int)
            or width <= 0
            or height <= 0
            or width * height > MAX_CELLS
        ):
            return _invalidate(name, topic, data, ts)
        grid = row.get("grid")
        if not isinstance(grid, list) or len(grid) > MAX_CELLS:
            return _invalidate(name, topic, data, ts)
        if grid and isinstance(grid[0], list):
            if len(grid) != height or any(not isinstance(line, list) or len(line) != width for line in grid):
                return _invalidate(name, topic, data, ts)
            cells = [value for line in grid for value in line]
        else:
            cells = grid
        if len(cells) != width * height or any(not _finite(value) for value in cells):
            return _invalidate(name, topic, data, ts)
        row["grid"] = list(cells)
        for field in ("resolution_m", "origin_x", "origin_y"):
            if field in row and not _finite(row[field]):
                return _invalidate(name, topic, data, ts)
        if "resolution_m" in row and row["resolution_m"] <= 0:
            return _invalidate(name, topic, data, ts)
    elif name == "path":
        path = row.get("path", [])
        if not isinstance(path, list) or len(path) > MAX_PATH:
            return _invalidate(name, topic, data, ts)
        points = [_point(point) for point in path]
        if any(point is None for point in points):
            return _invalidate(name, topic, data, ts)
        row["path"] = points
        if row.get("target") is not None:
            row["target"] = _point(row["target"])
            if row["target"] is None:
                return _invalidate(name, topic, data, ts)
    elif any(not _finite(row.get(key)) for key in ("x", "y", "theta")):
        return _invalidate(name, topic, data, ts)
    # Copy only the bounded fields consumed by the browser.
    allowed = {
        "map": ("width_cells", "height_cells", "grid", "resolution_m", "origin_x", "origin_y", "quality"),
        "pose": ("x", "y", "theta", "quality"),
        "path": ("path", "target", "quality"),
    }[name]
    bounded = {key: copy.deepcopy(row[key]) for key in allowed if key in row and key != "quality"}
    bounded.update(_metadata(data, topic, ts))
    return _store(name, bounded)


def snapshot() -> dict:
    with _lock:
        rows = copy.deepcopy(_rows)
    now = time.time()
    for name, row in rows.items():
        if row is not None:
            observed = row.get("observed_at")
            age = now - observed if _finite(observed) else None
            row["age_s"] = max(0.0, age) if age is not None else None
            row["stale"] = (
                row.get("stale") is True
                or row.get("offline") is True
                or bool(row.get("error"))
                or age is None
                or age < -0.1
                or age > (10 if name == "map" else 3)
            )
    path = rows["path"]
    if path and path.get("planning_only") is True:
        for name, source in (("map", rows["map"]), ("pose", rows["pose"])):
            if (
                source is None
                or frame_identity(source) != frame_identity(path)
                or confirmed_home(source) != confirmed_home(path)
            ):
                path.update(stale=True, planning_ready=False, error="plan_frame_mismatch")
            elif (
                not sample_status(source, max_age_s=3 if name == "map" else 0.5, now=now)["ready"]
                or source.get("data_ready") is not True
                or source.get("data_error")
                or "quality" in source
                and source["quality"] is None
                or isinstance(source.get("quality"), str)
                and source["quality"].lower() in {"unknown", "unavailable", "invalid", "error", "failed"}
                or source.get("planning_ready" if name == "map" else "navigation_ready") is not True
                or name == "pose"
                and not pose_status(source, max_age_s=0.5, now=now)["ready"]
                or name == "map"
                and (
                    not all(_finite(source.get(key)) for key in ("resolution_m", "origin_x", "origin_y"))
                    or source["resolution_m"] <= 0
                )
            ):
                path.update(stale=True, planning_ready=False, error="plan_sources_unavailable")
    return rows


def observe_plan(data: object) -> dict:
    """Project a passive point plan using its source age, never heartbeat age."""
    topic = "navigator.state"
    empty = {
        "planning_only": True,
        "goal_pose": None,
        "planned_path": [],
        "planned_path_length": 0,
        "planned_path_truncated": False,
        "plan_observed_at": None,
        "plan_calibration_id": None,
        "plan_reference_id": None,
        "plan_home": None,
    }
    if not isinstance(data, dict) or data.get("planning_only") is not True:
        _invalidate("path", topic, data)
        return {**empty, "planning_only": None}
    at = data.get("plan_observed_at")
    heartbeat = data.get("observed_at")
    path = data.get("planned_path")
    total = data.get("planned_path_length")
    truncated = data.get("planned_path_truncated")
    frame = {
        "calibration_id": data.get("plan_calibration_id"),
        "reference_id": data.get("plan_reference_id"),
        "home": data.get("plan_home"),
    }
    points = [_point(point) for point in path] if isinstance(path, list) and len(path) <= 128 else None
    target = _point(data.get("goal_pose"))
    valid = (
        _finite(at)
        and at > 0
        and _finite(heartbeat)
        and at <= heartbeat <= time.time() + 0.1
        and time.time() - heartbeat <= 3
        and frame_identity(frame) is not None
        and all(len(frame[key]) <= 512 for key in ("calibration_id", "reference_id"))
        and confirmed_home(frame) is not None
        and points is not None
        and bool(points)
        and all(point is not None for point in points)
        and target is not None
        and tuple(target) == confirmed_home(frame)
        and type(total) is int
        and len(points) <= total <= MAX_CELLS
        and type(truncated) is bool
        and truncated == (total > len(points))
        and not data.get("error")
        and data.get("data_ready") is True
        and data.get("data_error") in (None, "navigation_traversal_unverified")
        and data.get("stale") is not True
        and data.get("offline") is not True
    )
    if not valid:
        _invalidate("path", topic, data, at if _finite(at) and at > 0 else None)
        return empty
    row = {
        **frame,
        "observed_at": at,
        "path": points,
        "path_length": total,
        "path_truncated": truncated,
        "target": target,
        "planning_only": True,
        "planning_ready": True,
        "data_ready": True,
        "navigation_ready": False,
        "data_error": "navigation_traversal_unverified",
        "physical_completion": "unverified",
        "quality": "point_plan",
    }
    row["home"] = {
        key: frame["home"][key] for key in ("x", "y", "calibration_id", "reference_id", "operator_confirmed")
    }
    observe("navigator.path", row)
    return {
        "planning_only": True,
        "goal_pose": target,
        "planned_path": points,
        "planned_path_length": total,
        "planned_path_truncated": truncated,
        "plan_observed_at": at,
        "plan_calibration_id": frame["calibration_id"],
        "plan_reference_id": frame["reference_id"],
        "plan_home": copy.deepcopy(row["home"]),
        "physical_completion": "unverified",
    }
