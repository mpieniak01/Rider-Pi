#!/usr/bin/env python3
from __future__ import annotations

import os

from flask import Response, send_file

from . import compat as C


def track_ok(group: str) -> None:
    """
    Increment the OK counter for the specified API group.
    Thread-safe via API_METRICS_LOCK.
    """
    if group not in C.API_METRICS:
        return
    with C.API_METRICS_LOCK:
        C.API_METRICS[group]["ok"] += 1


def track_error(group: str) -> None:
    """
    Increment the error counter for the specified API group.
    Thread-safe via API_METRICS_LOCK.
    """
    if group not in C.API_METRICS:
        return
    with C.API_METRICS_LOCK:
        C.API_METRICS[group]["error"] += 1
        C.API_METRICS_TOTAL["errors"] += 1


def get_metrics_snapshot() -> dict:
    """
    Return a thread-safe snapshot of current metrics.
    """
    with C.API_METRICS_LOCK:
        metrics_snapshot = {group: dict(counts) for group, counts in C.API_METRICS.items()}
        total_errors = C.API_METRICS_TOTAL["errors"]
    return {
        "metrics": metrics_snapshot,
        "total_errors": total_errors,
    }


def dashboard():
    if not os.path.isfile(C.VIEW_HTML):
        return Response(
            "<h1>Rider-Pi API</h1><p>Brak web/view.html – użyj <a href='/state'>/state</a>, "
            "<a href='/sysinfo'>/sysinfo</a>, <a href='/healthz'>/healthz</a>.</p>",
            mimetype="text/html",
        ), 200
    return send_file(C.VIEW_HTML)


def control_page():
    if not os.path.isfile(C.CONTROL_HTML):
        return Response("<h1>control.html missing</h1>", mimetype="text/html"), 404
    return send_file(C.CONTROL_HTML)
