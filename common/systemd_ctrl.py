#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common import systemd_snapshot
from common.service_catalog import UNIT_CATALOG

BASE_DIR = Path(__file__).resolve().parents[1]
SERVICE_CTL = BASE_DIR / "scripts" / "service-systemd-backend.sh"
SYSTEMD_DIR = BASE_DIR / "systemd"
_DESC_CACHE: dict[str, str] = {}


@dataclass
class ActionResult:
    unit: str
    action: str
    method: str
    ok: bool
    rc: int
    stdout: str
    stderr: str
    skipped: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "action": self.action,
            "method": self.method,
            "ok": self.ok,
            "rc": self.rc,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "skipped": self.skipped,
        }


def _service_description_from_file(unit: str) -> str | None:
    filename = unit if unit.endswith(".service") else f"{unit}.service"
    cached = _DESC_CACHE.get(filename)
    if cached is not None:
        return cached
    candidate = SYSTEMD_DIR / filename
    if not candidate.exists():
        return None
    try:
        for line in candidate.read_text(encoding="utf-8").splitlines():
            if line.startswith("Description="):
                desc = line.split("=", 1)[1].strip()
                _DESC_CACHE[filename] = desc
                return desc
    except Exception:
        return None
    return None


def status(unit: str) -> dict[str, str]:
    """Zwróć status unitu systemd w spójnym formacie."""
    kv = systemd_snapshot.snapshot((unit,))[unit]
    desc = kv.get("desc", "").strip()
    if not desc or desc.lower() == unit.lower():
        file_desc = _service_description_from_file(unit)
        if file_desc:
            desc = file_desc
    return {**kv, "desc": desc}


def status_many(units: tuple[str, ...] | None = None, *, force: bool = False) -> dict[str, dict]:
    return systemd_snapshot.snapshot(units, force=force)


def invalidate_snapshot() -> None:
    systemd_snapshot.invalidate()


def is_loaded(unit: str) -> bool:
    """Czy unit istnieje (LoadState=loaded)?"""
    kv = status(unit)
    return kv.get("load") == "loaded" and not kv.get("error")


def is_active(unit: str) -> bool:
    """Czy unit jest aktywny (ActiveState=active)?"""
    kv = status(unit)
    return kv.get("active") == "active" and not kv.get("error")


def run_unit_action(unit: str, action: str, *, timeout: float = 25.0) -> ActionResult:
    """
    Uruchom akcję przez wspólny prywatny backend systemd.
    Dla stop/disable brakującego unitu zwraca wynik 'skipped'.
    """
    if unit not in UNIT_CATALOG or action not in {"start", "stop", "restart", "enable", "disable"}:
        return ActionResult(unit, action, "denied", False, 3, "", "unit/action outside canonical catalog")
    if action in {"stop", "disable"} and status(unit).get("load") == "not-found":
        return ActionResult(
            unit=unit,
            action=action,
            method="skipped",
            ok=True,
            skipped=True,
            rc=0,
            stdout="",
            stderr="",
        )

    invalidate_snapshot()
    use_script = SERVICE_CTL.exists() and os.access(SERVICE_CTL, os.X_OK)
    if use_script:
        proc = subprocess.run(
            ["sudo", "-n", str(SERVICE_CTL), unit, action],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        invalidate_snapshot()
        return ActionResult(
            unit=unit,
            action=action,
            method="script",
            ok=proc.returncode == 0,
            rc=proc.returncode,
            stdout=(proc.stdout or "")[-4000:],
            stderr=(proc.stderr or "")[-4000:],
        )

    return ActionResult(unit, action, "unavailable", False, 3, "", "service_backend_unavailable")


__all__ = [
    "ActionResult",
    "is_active",
    "is_loaded",
    "run_unit_action",
    "status",
    "status_many",
    "invalidate_snapshot",
]
