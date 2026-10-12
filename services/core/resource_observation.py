"""Briefly cached read-only ownership, shared by all status projections."""

from __future__ import annotations

import threading
import time
from copy import deepcopy

_CACHE = {}
_LOCK = threading.Lock()


def invalidate(name):
    with _LOCK:
        _CACHE.pop(name, None)


def snapshot(name, *, probe=None, clock=time.monotonic):
    from services.api_core.resource_diag import inspect

    probe = inspect if probe is None else probe
    with _LOCK:
        previous = _CACHE.get(name)
        if previous and previous[0] is probe and 0 <= clock() - previous[1] < 3:
            return deepcopy(previous[2])
        try:
            result = probe(name)
        except Exception as error:
            result = {"free": None, "state": "unknown", "holders": [], "error": type(error).__name__}
        _CACHE[name] = (probe, clock(), deepcopy(result))
        return result
