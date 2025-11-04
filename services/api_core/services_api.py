#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from flask import Response, request

from . import compat as C

# --- whitelist aliasów -> pełne nazwy unitów ---
ALLOWED_UNITS: dict[str, str] = {
    # core
    "api": "rider-api.service",
    "broker": "rider-broker.service",
    "web": "rider-web-bridge.service",
    # voice
    "voice": "rider-voice.service",
    "voice-web": "rider-voice-web.service",
    # motion / xgo
    "xgo": "rider-motion-bridge.service",
    "motion": "rider-motion-bridge.service",
    "motion-preview": "rider-motion-bridge.service",
    # camera pipelines (preview)
    "cam": "rider-cam-preview.service",
    "camera": "rider-cam-preview.service",
    "edge": "rider-edge-preview.service",
    "ssd": "rider-ssd-preview.service",
    # detectors
    "obstacle": "rider-obstacle.service",
    # legacy aliases
    "last": "rider-ssd-preview.service",
    "lastframe": "rider-ssd-preview.service",
    # new units added
    "mapper": "rider-mapper.service",
    "odometry": "rider-odometry.service",
    "tracker": "rider-tracker.service",
    # "post-splash": "rider-post-splash.service",
    "google-bridge": "rider-google-bridge.service",
    "tracking-controller": "rider-tracking-controller.service",
}


# --- grupy wzajemnie wykluczające (mutex) ---
MUTEX_GROUPS: list[set[str]] = [
    {
        "rider-cam-preview.service",
        "rider-edge-preview.service",
        "rider-ssd-preview.service",
    },
]

# dozwolone akcje
ALLOWED_ACTIONS: tuple[str, ...] = ("start", "stop", "restart", "enable", "disable")

SERVICE_CTL = os.path.join(C.BASE_DIR, "scripts", "sys_control.sh")


# -------------------- helpers --------------------
def _json(payload: Any, status: int = 200) -> Response:
    return Response(
        json.dumps(payload, ensure_ascii=False),
        mimetype="application/json",
        status=status,
    )


def _unit_for(name: str | None) -> str | None:
    """Zwraca pełną nazwę unitu (whitelist); akceptuje alias lub pełną nazwę z whitelisty."""
    if not name:
        return None
    key = (name or "").strip().lower()
    if key in ALLOWED_UNITS:
        return ALLOWED_UNITS[key]
    if key in ALLOWED_UNITS.values():
        return key
    return None


def _svc_show(unit: str) -> dict[str, str]:
    """systemctl show → dict z polami stanu (bez wyjątków)."""
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
            timeout=3.0,
        )
    except Exception as e:
        return {"error": str(e), "unit": unit}
    kv: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip()
    kv["unit"] = unit
    return kv


def _svc_status(unit: str) -> dict[str, str]:
    kv = _svc_show(unit)
    if "error" in kv:
        return {"unit": unit, "error": kv["error"]}
    return {
        "unit": unit,
        "load": kv.get("LoadState", ""),
        "active": kv.get("ActiveState", ""),
        "sub": kv.get("SubState", ""),
        "enabled": kv.get("UnitFileState", ""),
        "desc": kv.get("Description", ""),
    }


def _unit_loaded(unit: str) -> bool:
    """Czy unit istnieje (LoadState=loaded)?"""
    kv = _svc_show(unit)
    return kv.get("LoadState") == "loaded"


def _conflicts(unit: str) -> list[str]:
    """Jednostki z tej samej grupy mutex (poza samym unitem)."""
    out: list[str] = []
    for grp in MUTEX_GROUPS:
        if unit in grp:
            out.extend(sorted(u for u in grp if u != unit))
    return out


def _build_sequence(unit: str, action: str) -> list[tuple[str, str]]:
    """
    Zwróć sekwencję kroków (unit, action) z uwzględnieniem konfliktów.
    - start/restart: najpierw stop konfliktów, potem start/restart celu
    - restart: rozbijamy na stop→start (czyściej)
    """
    steps: list[tuple[str, str]] = []
    if action in {"start", "restart"}:
        for u in _conflicts(unit):
            steps.append((u, "stop"))
        if action == "restart":
            steps.append((unit, "stop"))
            steps.append((unit, "start"))
        else:
            steps.append((unit, "start"))
    elif action in {"stop", "enable", "disable"}:
        steps.append((unit, action))
    else:
        steps.append((unit, action))
    return steps


def _run_via_systemctl(unit: str, action: str) -> dict[str, Any]:
    """Fallback: wykonaj akcję bezpośrednio przez systemctl (sudo -n)."""
    proc = subprocess.run(
        ["sudo", "-n", "systemctl", action, unit],
        check=False,
        capture_output=True,
        text=True,
        timeout=25.0,
    )
    return {
        "unit": unit,
        "action": action,
        "method": "systemctl",
        "ok": proc.returncode == 0,
        "rc": proc.returncode,
        "stdout": (proc.stdout or "")[-4000:],
        "stderr": (proc.stderr or "")[-4000:],
    }


def _run_step(unit: str, action: str) -> dict[str, Any]:
    """
    Uruchom pojedynczy krok przez sys_control.sh; jeśli brak skryptu lub +x,
    wykonaj bezpośrednio przez systemctl (sudo -n).
    Jeśli unit nie istnieje i akcja to 'stop'/'disable' – oznacz jako 'skipped'.
    """
    if action in {"stop", "disable"} and not _unit_loaded(unit):
        return {
            "unit": unit,
            "action": action,
            "method": "skipped",
            "ok": True,
            "skipped": True,
            "rc": 0,
            "stdout": "",
            "stderr": "",
        }

    if not os.path.isfile(SERVICE_CTL) or not os.access(SERVICE_CTL, os.X_OK):
        return _run_via_systemctl(unit, action)

    proc = subprocess.run(
        ["sudo", "-n", SERVICE_CTL, unit, action],
        check=False,
        capture_output=True,
        text=True,
        timeout=25.0,
    )
    return {
        "unit": unit,
        "action": action,
        "method": "script",
        "ok": proc.returncode == 0,
        "rc": proc.returncode,
        "stdout": (proc.stdout or "")[-4000:],
        "stderr": (proc.stderr or "")[-4000:],
    }


# -------------------- endpoints --------------------
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

    if action not in ALLOWED_ACTIONS:
        return _json({"error": "bad action", "allowed": list(ALLOWED_ACTIONS)}, status=400)

    # BEZPIECZNIK: nie pozwalaj zatrzymać/restartować samego API przez API
    if unit == "rider-api.service" and action in {"stop", "restart"}:
        return _json(
            {
                "ok": False,
                "error": "forbidden_on_api",
                "hint": "Zatrzymywanie/restart API wykonaj przez systemctl w shellu.",
                "unit": unit,
                "action": action,
            },
            status=409,
        )

    # zbuduj sekwencję kroków (uwzględnia konflikty)
    steps = _build_sequence(unit, action)

    results: list[dict[str, Any]] = []
    for u, a in steps:
        results.append(_run_step(u, a))

    # końcowy status celu
    status_obj = _svc_status(unit)

    # sukces: wszystkie kroki ok LUB docelowy krok ok
    ok_all = all(r.get("ok") for r in results)
    ok_target = any(r.get("ok") and r["unit"] == unit for r in results) if results else False
    ok = ok_all or ok_target

    payload = {
        "ok": ok,
        "sequence": steps,
        "results": results,
        "status": status_obj,
    }
    return _json(payload, status=(200 if ok else 500))


try:
    from .services_dashboard_api import bp as _services_dashboard_bp
except Exception as exc:
    if hasattr(C, 'app'):
        C.app.logger.warning('[api] failed to import services dashboard blueprint: %s', exc)
else:
    if hasattr(C, 'app') and _services_dashboard_bp.name not in C.app.blueprints:
        C.app.register_blueprint(_services_dashboard_bp)
        C.app.logger.info('[api] services dashboard blueprint registered: /api/services/*')
