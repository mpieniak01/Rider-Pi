"""A bounded, shared systemd observation cache (one show process per refresh)."""

from __future__ import annotations

import subprocess
import threading
import time

from common.service_catalog import UNIT_CATALOG

_LOCK = threading.RLock()
_CACHE: dict[str, dict] = {}
_LAST_REFRESH = 0.0
TTL_SECONDS = 0.75
PROPERTIES = "Id,LoadState,ActiveState,SubState,UnitFileState,Description,MainPID,ActiveEnterTimestamp,Wants,Requires"


def parse_show(output: str) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    for block in output.strip().split("\n\n"):
        row = {}
        for line in block.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                row[key.strip()] = value.strip()
        if row.get("Id"):
            records[row["Id"]] = row
    return records


def invalidate() -> None:
    global _LAST_REFRESH
    with _LOCK:
        _LAST_REFRESH = 0.0


def _normalize(unit: str, values: dict, observed_at: float, error: str | None = None) -> dict:
    load = values.get("LoadState", "unknown")
    active = values.get("ActiveState", "unknown")
    try:
        pid = int(values.get("MainPID", "0"))
    except ValueError:
        pid = 0
    return {
        "unit": unit,
        "host": "pi",
        "source": "systemd",
        "observed_at": observed_at,
        "stale": bool(error),
        "load": load,
        "active": active,
        "sub": values.get("SubState", "unknown"),
        "enabled": values.get("UnitFileState", "unknown"),
        "installed": load == "loaded" and not error,
        "desc": values.get("Description", ""),
        "pid": pid,
        "since": values.get("ActiveEnterTimestamp") or None,
        "wants": values.get("Wants", "").split(),
        "requires": values.get("Requires", "").split(),
        "error": error,
    }


def snapshot(units: tuple[str, ...] | None = None, *, force: bool = False) -> dict[str, dict]:
    global _CACHE, _LAST_REFRESH
    requested = units or tuple(UNIT_CATALOG)
    with _LOCK:
        now = time.monotonic()
        if force or now - _LAST_REFRESH >= TTL_SECONDS or any(unit not in _CACHE for unit in requested):
            all_units = tuple(sorted(set(UNIT_CATALOG) | set(requested)))
            observed_at = time.time()
            try:
                proc = subprocess.run(
                    ["systemctl", "show", *all_units, "--no-page", f"--property={PROPERTIES}"],
                    capture_output=True,
                    text=True,
                    timeout=4,
                    check=False,
                )
                values = parse_show(proc.stdout)
                error = (
                    (proc.stderr.strip() or "systemd observation failed") if proc.returncode and not values else None
                )
                _CACHE = {
                    unit: _normalize(
                        unit,
                        values.get(unit, {}),
                        observed_at,
                        error or ("unit observation missing" if unit not in values else None),
                    )
                    for unit in all_units
                }
            except (OSError, subprocess.SubprocessError) as exc:
                # Retain last observed values, but explicitly lose readiness.
                _CACHE = {
                    unit: {
                        **_CACHE.get(unit, _normalize(unit, {}, observed_at)),
                        "stale": True,
                        "installed": False,
                        "error": str(exc),
                    }
                    for unit in all_units
                }
            _LAST_REFRESH = now
        return {unit: dict(_CACHE[unit]) for unit in requested}
