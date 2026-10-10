"""Read-only version metadata for the repository serving the Pi dashboard."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify

bp = Blueprint("version", __name__, url_prefix="/api/status")
REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_TTL = 60.0
GIT_TIMEOUT = 1.0
_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_cache_until = 0.0


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
        check=False,
    )
    if result.returncode:
        if args[0] == "symbolic-ref" and result.returncode == 1:
            return "HEAD"
        raise ValueError("Git metadata unavailable")
    return result.stdout.strip()


def get_version_info() -> dict[str, Any]:
    """Cache successful and unavailable results; never change repository state."""
    global _cache, _cache_until
    with _lock:
        if _cache is not None and time.monotonic() < _cache_until:
            return dict(_cache)
        payload: dict[str, Any] = {
            "available": False,
            "branch": "unknown",
            "commit": None,
            "dirty": False,
            "message": "",
            "ts": time.time(),
        }
        try:
            commit = _git("rev-parse", "--verify", "HEAD")
            if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
                raise ValueError("Invalid commit metadata")
            branch = _git("symbolic-ref", "--quiet", "--short", "HEAD")
            dirty = bool(_git("status", "--porcelain", "--untracked-files=normal"))
            message = _git("log", "-1", "--format=%s")
            payload.update(available=True, branch=branch, commit=commit[:7], dirty=dirty, message=message)
        except (OSError, subprocess.SubprocessError, ValueError):
            # A missing Git binary, checkout or slow command must not break the UI.
            payload["available"] = False
        _cache = payload
        _cache_until = time.monotonic() + CACHE_TTL
        return dict(payload)


@bp.route("/version", methods=["GET"])
def version_info():
    response = jsonify(get_version_info())
    response.headers["Cache-Control"] = "no-store"
    return response
