"""One passive frame resolver for image routes and their metadata."""

from __future__ import annotations

import math
import mimetypes
import os
import time
from pathlib import Path

from flask import jsonify, make_response, request, send_file

from . import compat as C

STREAMS = {
    "raw": ("RAW_PATH", "raw", "/camera/raw"),
    "proc": ("PROC_PATH", "proc", "/camera/proc"),
    "ssd": ("SSD_PATH", "ssd", "/vision/ssd"),
    "obst": ("OBST_PATH", "obst_annot", "/vision/obst"),
    "tracker": ("TRACKER_PATH", "tracker", "/vision/tracker"),
}
MAX_AGE_S = min(3.0, max(0.1, float(os.getenv("SNAP_MAX_AGE_S", "3"))))


def resolve(stream: str) -> Path:
    attribute, base, _ = STREAMS[stream]
    configured = os.getenv(attribute) or getattr(C, attribute, None)
    default = Path(configured) if configured else Path(C.SNAP_DIR) / (base + ".jpg")
    candidates = [default]
    for name in (base, "cam") if stream == "raw" else (base,):
        candidates.extend(Path(C.SNAP_DIR) / (name + ext) for ext in (".jpg", ".png", ".bmp"))
    return next((path for path in candidates if path.is_file()), default)


def describe(stream: str, *, path=None, now=None, archive=False) -> dict:
    now = time.time() if now is None else now
    selected = Path(path) if path is not None else resolve(stream)
    at = None
    size = None
    error = None
    try:
        stat = selected.stat()
        at = stat.st_mtime if math.isfinite(stat.st_mtime) and stat.st_mtime > 0 else None
        size = stat.st_size
        exists = selected.is_file()
    except FileNotFoundError:
        exists, error = False, "frame_not_found"
    except OSError:
        exists, error = False, "frame_unavailable"
    age = now - at if at is not None else None
    stale = age is None or not -0.1 <= age <= MAX_AGE_S
    if exists and at is None:
        error = "frame_time_unknown"
    elif exists and age < -0.1:
        error = "frame_clock_future"
    elif exists and stale:
        error = "frame_stale"
    return {
        "stream": stream,
        "url": STREAMS[stream][2],
        "path": str(selected),
        "exists": exists,
        "frame_id": f"{stream}:{at}:{size}" if exists and at is not None else None,
        "observed_at": None,
        "capture_at": None,
        "file_observed_at": at,
        "source": "filesystem",
        "provenance": "file_mtime",
        "stale": stale,
        "error": error,
        "placeholder": False,
        "max_age_s": MAX_AGE_S,
        "archive": archive,
        "mtime": int(at) if at is not None else None,
        "size": size,
        "age_s": age,
    }


def headers(response, row):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Rider-Contract"] = "rider.frames;version=1"
    response.headers["X-Rider-Source"] = row["source"]
    response.headers["X-Rider-Stream"] = row["stream"]
    response.headers["X-Rider-Stale"] = "true" if row["stale"] else "false"
    response.headers["X-Rider-Placeholder"] = "true" if row["placeholder"] else "false"
    if row.get("frame_id"):
        response.headers["X-Rider-Frame-Id"] = row["frame_id"]
    if row.get("file_observed_at") is not None:
        response.headers["X-Rider-File-Observed-At"] = str(row["file_observed_at"])
    return response


def response(stream: str, *, path=None, archive=None):
    archive = request.args.get("archive") == "1" if archive is None else archive
    row = describe(stream, path=path, archive=archive)
    if not row["exists"] or row["stale"] and not archive:
        return headers(make_response(jsonify({"ok": False, "error": row["error"], "frame": row}), 404), row)
    mime = mimetypes.guess_type(row["path"])[0] or "application/octet-stream"
    result = make_response(send_file(row["path"], mimetype=mime, conditional=False))
    return headers(result, row)
