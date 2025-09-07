#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, subprocess, json
from typing import Optional
from flask import Response, request
from . import compat as C

ALLOWED_UNITS = {
    "vision":    "rider-vision.service",
    "last":      "rider-ssd-preview.service",
    "lastframe": "rider-ssd-preview.service",
    "xgo":       "rider-motion-bridge.service",
}
SERVICE_CTL = os.path.join(C.BASE_DIR, "ops", "service_ctl.sh")


def _json(payload, status: int = 200) -> Response:
    return Response(json.dumps(payload, ensure_ascii=False),
                    mimetype="application/json", status=status)


def _unit_for(name: str) -> Optional[str]:
    if name in ALLOWED_UNITS:
        return ALLOWED_UNITS[name]
    if name in ALLOWED_UNITS.values():
        return name
    return None


def _svc_status(unit: str) -> dict:
    try:
        out = subprocess.check_output(
            [
                "systemctl", "show", unit, "--no-page",
                "--property=ActiveState,SubState,UnitFileState,LoadState,Description"
            ],
            stderr=subprocess.STDOUT, text=True, timeout=2.0
        )
        kv = {}
        for line in out.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                kv[k.strip()] = v.strip()
        return {
            "unit": unit,
            "load": kv.get("LoadState"),
            "active": kv.get("ActiveState"),
            "sub": kv.get("SubState"),
            "enabled": kv.get("UnitFileState"),
            "desc": kv.get("Description")
        }
    except Exception as e:
        return {"unit": unit, "error": str(e)}


def svc_list():
    services = [_svc_status(u) for u in sorted(set(ALLOWED_UNITS.values()))]
    return _json({"services": services})


def svc_status(name: str):
    name = (name or "").strip().lower()
    unit = _unit_for(name)
    if not unit:
        return _json({"error": "unknown service"}, status=404)
    return _json(_svc_status(unit))


def svc_action(name: str):
    name = (name or "").strip().lower()
    unit = _unit_for(name)
    if not unit:
        return _json({"error": "unknown service"}, status=404)

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    if action not in ("start", "stop", "restart", "enable", "disable"):
        return _json({"error": "bad action"}, status=400)

    if not os.path.isfile(SERVICE_CTL) or not os.access(SERVICE_CTL, os.X_OK):
        return _json(
            {"error": "service_ctl_missing",
             "hint": "chmod +x ops/service_ctl.sh & add sudoers NOPASSWD"},
            status=501
        )

    try:
        proc = subprocess.run(
            ["sudo", "-n", SERVICE_CTL, unit, action],
            check=False, capture_output=True, text=True, timeout=8.0
        )
        status_obj = _svc_status(unit)
        payload = {
            "ok": (proc.returncode == 0),
            "rc": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-4000:],
            "status": status_obj
        }
        return _json(payload, status=(200 if proc.returncode == 0 else 500))
    except subprocess.TimeoutExpired:
        return _json({"error": "timeout"}, status=504)
    except Exception as e:
        return _json({"error": str(e)}, status=500)
