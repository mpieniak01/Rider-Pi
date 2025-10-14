#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from flask import Response, request

from . import compat as C

# Pełna, jawna whitelist’a (alias -> unit)
ALLOWED_UNITS: dict[str, str] = {
    # core
    "api": "rider-api.service",
    "broker": "rider-broker.service",
    "web": "rider-web-bridge.service",
    # motion / xgo
    # Uwaga: u Ciebie realny unit to rider-motion-bridge.service — aliasy dla kompatybilności
    "xgo": "rider-motion-bridge.service",
    "motion": "rider-motion-bridge.service",
    "motion-preview": "rider-motion-bridge.service",  # jeśli masz osobny unit, podmień na rider-motion-preview.service
    # camera pipelines
    "cam": "rider-cam-preview.service",
    "camera": "rider-cam-preview.service",  # legacy alias
    "edge": "rider-edge-preview.service",
    "ssd": "rider-ssd-preview.service",
    # detectors
    "obstacle": "rider-obstacle.service",
    # legacy aliasy zgodne z dawnym UI / API
    "last": "rider-ssd-preview.service",
    "lastframe": "rider-ssd-preview.service",
}

SERVICE_CTL = os.path.join(C.BASE_DIR, "scripts", "sys_control.sh")


def _json(payload: Any, status: int = 200) -> Response:
    return Response(
        json.dumps(payload, ensure_ascii=False),
        mimetype="application/json",
        status=status,
    )


def _unit_for(name: str | None) -> str | None:
    """Zwraca pełną nazwę unitu (whitelist), akceptuje alias lub pełną nazwę."""
    if not name:
        return None
    key = name.strip().lower()
    # alias
    if key in ALLOWED_UNITS:
        return ALLOWED_UNITS[key]
    # pełna nazwa (tylko jeżeli jest w wartościach whitelisty)
    allowed_values = ALLOWED_UNITS.values()
    if key in allowed_values:
        return key
    return None


def _svc_status(unit: str) -> dict[str, str]:
    try:
        out = subprocess.check_output(
            [
                "systemctl",
                "show",
                unit,
                "--no-page",
                "--property=ActiveState,SubState,UnitFileState,LoadState,Description",
            ],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=2.0,
        )
        kv: dict[str, str] = {}
        for line in out.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                kv[k.strip()] = v.strip()
        return {
            "unit": unit,
            "load": kv.get("LoadState", ""),
            "active": kv.get("ActiveState", ""),
            "sub": kv.get("SubState", ""),
            "enabled": kv.get("UnitFileState", ""),
            "desc": kv.get("Description", ""),
        }
    except Exception as e:
        return {"unit": unit, "error": str(e)}


def svc_list() -> Response:
    """Zwraca statusy wszystkich unikalnych unitów z whitelisty."""
    unique_units = sorted(set(ALLOWED_UNITS.values()))
    services = [_svc_status(u) for u in unique_units]
    return _json({"services": services})


def svc_status(name: str) -> Response:
    unit = _unit_for(name or "")
    if not unit:
        return _json({"error": "unknown service", "name": name}, status=404)
    return _json(_svc_status(unit))


def svc_action(name: str) -> Response:
    unit = _unit_for(name or "")
    if not unit:
        return _json({"error": "unknown service", "name": name}, status=404)

    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "").strip().lower()
    if action not in {"start", "stop", "restart", "enable", "disable"}:
        return _json({"error": "bad action", "allowed": ["start", "stop", "restart", "enable", "disable"]}, status=400)

    if not os.path.isfile(SERVICE_CTL) or not os.access(SERVICE_CTL, os.X_OK):
        return _json(
            {
                "error": "service_ctl_missing",
                "hint": "chmod +x scripts/sys_control.sh oraz dodaj sudoers NOPASSWD dla systemctl",
            },
            status=501,
        )

    try:
        # API woła w kolejności: UNIT potem ACTION
        proc = subprocess.run(
            ["sudo", "-n", SERVICE_CTL, unit, action],
            check=False,
            capture_output=True,
            text=True,
            timeout=12.0,
        )
        status_obj = _svc_status(unit)
        payload = {
            "ok": proc.returncode == 0,
            "rc": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-4000:],
            "status": status_obj,
        }
        return _json(payload, status=(200 if proc.returncode == 0 else 500))
    except subprocess.TimeoutExpired:
        return _json({"error": "timeout", "unit": unit, "action": action}, status=504)
    except Exception as e:
        return _json({"error": str(e), "unit": unit, "action": action}, status=500)
