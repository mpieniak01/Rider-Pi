"""Bounded presentation cache; read-only snapshots never start navigation."""

from __future__ import annotations

import copy
import math
import threading
import time

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
    for key in ("stale", "offline", "data_ready", "navigation_ready"):
        if type(data.get(key)) is bool:
            row[key] = data[key]
    for key in ("error", "data_error", "calibration_id"):
        if isinstance(data.get(key), str):
            row[key] = data[key][:512]
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
    with _lock:
        previous = _rows[name]
        if previous is not None and _finite(previous.get("observed_at")) and _finite(row.get("observed_at")):
            if previous["observed_at"] > row["observed_at"] and healthy:
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
    return rows
