"""On-demand journal projection, restricted to the common unit catalog."""

from __future__ import annotations

import os
import selectors
import subprocess
import time

MAX_BYTES = 65536
MAX_LINES = 50
TIMEOUT_S = 2.0


def _read_ready(selector, buffers, ready):
    for key, _mask in ready:
        chunk = os.read(key.fd, 4096)
        if not chunk:
            selector.unregister(key.fileobj)
            continue
        total = sum(len(value) for value in buffers.values())
        buffers[key.data].extend(chunk[: MAX_BYTES - total])
        if total + len(chunk) >= MAX_BYTES:
            return True
    return False


def _read_streams(process, buffers, deadline):
    timed_out = truncated = False
    with selectors.DefaultSelector() as selector:
        for name in buffers:
            pipe = getattr(process, name)
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            truncated = _read_ready(selector, buffers, selector.select(remaining))
            if truncated:
                break
    return timed_out, truncated


def _journal(command: list[str]) -> dict:
    """Bound both time and bytes; never execute a shell or privilege helper."""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + TIMEOUT_S
    timed_out = truncated = False
    try:
        timed_out, truncated = _read_streams(process, buffers, deadline)
        if process.poll() is None:
            if timed_out or truncated:
                process.kill()
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait(timeout=0.5)
    finally:
        for name in buffers:
            getattr(process, name).close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=0.5)
    return {
        "returncode": process.returncode,
        "stdout": buffers["stdout"].decode("utf-8", errors="replace"),
        "stderr": buffers["stderr"].decode("utf-8", errors="replace"),
        "timeout": timed_out,
        "truncated": truncated,
    }


def read_logs(unit: str, *, catalog=None, runner=None) -> dict:
    result = {"ok": False, "unit": unit, "source": "pi/systemd/journal", "observed_at": None, "lines": []}
    if catalog is None:
        try:
            from common.service_catalog import UNIT_CATALOG

            catalog = UNIT_CATALOG
        except ImportError:
            return dict(result, error="catalog_unavailable")
    if unit not in catalog:
        return dict(result, error="unit_not_in_catalog")
    command = ["/usr/bin/journalctl", "--no-pager", "--quiet", "--output=short-iso", "-n", str(MAX_LINES), "-u", unit]
    try:
        completed = (runner or _journal)(command)
    except (OSError, subprocess.SubprocessError) as exc:
        return dict(result, error=str(exc)[:512])
    if completed.get("timeout"):
        return dict(result, error="journal_timeout")
    if completed.get("stderr", "").strip():
        return dict(result, error=completed["stderr"][:512])
    if completed.get("returncode") != 0 and not completed.get("truncated"):
        return dict(result, error="journal_unavailable")
    output = completed.get("stdout", "")[:MAX_BYTES]
    return dict(
        result,
        ok=True,
        observed_at=time.time(),
        lines=output.splitlines()[:MAX_LINES],
        truncated=bool(completed.get("truncated")),
    )


def service_logs(unit: str):
    from flask import jsonify

    result = read_logs(unit)
    code = 200 if result["ok"] else 404 if result.get("error") == "unit_not_in_catalog" else 503
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response, code
