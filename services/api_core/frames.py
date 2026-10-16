"""One passive frame resolver for image routes and their metadata."""

from __future__ import annotations

import json
import math
import mimetypes
import os
import stat
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


def _ram_description(stream, selected, now):
    from apps.camera.pipeline_ipc import read_frame

    try:
        item = read_frame(metadata_only=True, view="raw" if stream == "raw" else "proc")
    except (OSError, ValueError, KeyError, TypeError):
        item = None
    metadata = item[1] if item is not None else None
    age = metadata["frame_age_ms"] / 1000 if metadata else None
    return {
        "stream": stream,
        "url": STREAMS[stream][2],
        "path": str(selected),
        "exists": metadata is not None,
        "frame_id": metadata["frame_id"] if metadata else None,
        "observed_at": now - age if age is not None else None,
        "capture_at": now - age if age is not None else None,
        "file_observed_at": None,
        "source": "camera_pipeline_ram",
        "provenance": "capture",
        "stale": age is None or age > MAX_AGE_S,
        "error": "frame_unavailable" if metadata is None else "frame_stale" if age > MAX_AGE_S else None,
        "placeholder": False,
        "max_age_s": MAX_AGE_S,
        "archive": False,
        "mtime": None,
        "size": None,
        "age_s": age,
    }


def describe(stream: str, *, path=None, now=None, archive=False, stat_result=None) -> dict:
    now = time.time() if now is None else now
    from services.camera_pipeline_store import enabled

    use_ram = enabled() and path is None and not archive and stream in {"raw", "proc", "ssd"}
    selected = (
        Path(path)
        if path is not None
        else (Path(C.SNAP_DIR) / (STREAMS[stream][1] + ".jpg") if use_ram else resolve(stream))
    )
    if use_ram:
        return _ram_description(stream, selected, now)
    at = None
    size = None
    error = None
    try:
        metadata = selected.stat() if stat_result is None else stat_result
        at = metadata.st_mtime if math.isfinite(metadata.st_mtime) and metadata.st_mtime > 0 else None
        size = metadata.st_size
        exists = stat.S_ISREG(metadata.st_mode)
        if not exists:
            error = "frame_unavailable"
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


def _ram_response(stream):
    from services.api_core.camera_pipeline_api import frame

    result = make_response(frame(view="raw" if stream == "raw" else "proc"))
    encoded = result.headers.pop("X-Rider-Source", None)
    source = json.loads(encoded) if encoded else None
    age = None
    if source is not None:
        # The descriptor and the body come from the same RAM read. A second
        # metadata lookup could label this JPEG with the next frame instead.
        measured = (time.monotonic_ns() - source["captured_monotonic_ns"]) / 1_000_000
        reported = source["frame_age_ms"]
        if math.isfinite(measured) and math.isfinite(reported) and measured >= 0 and reported >= 0:
            age = max(measured, reported)
            source = dict(source, frame_age_ms=age)
    stale = age is None or age > MAX_AGE_S * 1000
    row = {
        "source": "pi-camera",
        "stream": stream,
        "stale": stale,
        "placeholder": False,
        "frame_id": source.get("frame_id") if source else None,
    }
    result = headers(result, row)
    if source is not None:
        result.headers["X-Rider-Source-Json"] = json.dumps(source, separators=(",", ":"))
        for key, header in (
            ("sequence", "Sequence"),
            ("camera_session", "Camera-Session"),
            ("transport_epoch", "Transport-Epoch"),
            ("pipeline_revision", "Pipeline-Revision"),
            ("captured_monotonic_ns", "Captured-Monotonic-Ns"),
        ):
            result.headers["X-Rider-" + header] = str(source[key])
        if age is not None:
            result.headers["X-Rider-Frame-Age-Ms"] = str(age)
            result.headers["X-Rider-Frame-Age-Source"] = "capture"
            result.headers["X-Rider-Observed-At"] = str(time.time() - age / 1000)
        result.headers["X-Rider-Provenance"] = "capture"
    return result


def response(stream: str, *, path=None, archive=None):
    from services.camera_pipeline_store import enabled

    if (
        enabled()
        and path is None
        and archive is None
        and request.args.get("archive") != "1"
        and stream in {"raw", "proc", "ssd"}
    ):
        return _ram_response(stream)
    archive = request.args.get("archive") == "1" if archive is None else archive
    selected = Path(path) if path is not None else resolve(stream)
    descriptor = None
    handle = None
    try:
        try:
            # Atomic camera replacement must not change the inode between
            # metadata and transfer. NONBLOCK also makes FIFO races harmless.
            descriptor = os.open(selected, os.O_RDONLY | os.O_NONBLOCK)
            metadata = os.fstat(descriptor)
            row = describe(stream, path=selected, archive=archive, stat_result=metadata)
            if not row["exists"] or row["stale"] and not archive:
                return headers(make_response(jsonify({"ok": False, "error": row["error"], "frame": row}), 404), row)
            handle = os.fdopen(descriptor, "rb")
            descriptor = None
        except OSError as exc:
            row = describe(stream, path=selected, archive=archive)
            row.update(
                exists=False,
                stale=True,
                error="frame_not_found" if isinstance(exc, FileNotFoundError) else "frame_unavailable",
            )
            return headers(make_response(jsonify({"ok": False, "error": row["error"], "frame": row}), 404), row)
        mime = mimetypes.guess_type(str(selected))[0] or "application/octet-stream"
        result = make_response(
            send_file(handle, mimetype=mime, conditional=False, last_modified=row["file_observed_at"])
        )
        result.content_length = row["size"]
        result.call_on_close(handle.close)
        result = headers(result, row)
        # Werkzeug's file wrapper owns this descriptor until transfer closes.
        handle = None
        return result
    finally:
        if handle is not None:
            handle.close()
        if descriptor is not None:
            os.close(descriptor)
