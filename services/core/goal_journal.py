"""Restore observed passive goal ownership after an API restart, never actuators."""

from __future__ import annotations

import json
from pathlib import Path

from common.service_catalog import PROTECTED_UNITS, UNIT_CATALOG, task_units


def boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return None


def identity(row):
    pid, since = row.get("pid"), row.get("since")
    if type(pid) is not int or pid < 0 or not isinstance(since, str) or not since:
        return None
    if row.get("active") != "active" or row.get("stale") or row.get("error"):
        return None
    return {"pid": pid, "since": since}


def journal(manager):
    watched = set(manager._managed_units) | set(manager._admin_units)
    for name, options in manager._requested.items():
        if not manager.registry[name].can_move:
            watched.update(task_units(manager.registry[name], options))
    return {
        "version": 1,
        "boot_id": boot_id(),
        "goals": {
            name: options
            for name, options in manager._requested.items()
            if name != "s0_core" and not manager.registry[name].can_move
        },
        "identities": {unit: identity(manager._status(unit)) for unit in watched if unit not in PROTECTED_UNITS},
        "managed": sorted(manager._managed_units),
        "admin": sorted(manager._admin_units),
        "domains": dict(manager._service_domains),
    }


def _identity_matches(manager, saved, unit):
    expected = saved.get(unit)
    return isinstance(expected, dict) and expected == identity(manager._status(unit))


def _restore_passive_goals(manager, data, saved):
    goals = data.get("goals", {})
    if not isinstance(goals, dict):
        return None
    restored_units = set()
    for name, options in goals.items():
        feature = manager.registry.get(name)
        if feature is None or feature.can_move or not isinstance(options, dict):
            continue
        try:
            units = set(task_units(feature, options)) - PROTECTED_UNITS
        except (ValueError, TypeError):
            continue
        if units and all(_identity_matches(manager, saved, unit) for unit in units):
            manager._requested[name] = dict(options)
            restored_units.update(units)
    return restored_units


def _restore_admin_units(manager, admin, saved):
    if isinstance(admin, list):
        for unit in admin:
            if (
                isinstance(unit, str)
                and unit in UNIT_CATALOG
                and not UNIT_CATALOG[unit]["can_move"]
                and _identity_matches(manager, saved, unit)
            ):
                manager._admin_units.add(unit)


def restore(manager):
    if manager._restored:
        return
    manager._restored = True
    try:
        if manager._state_path.stat().st_size > 256 * 1024:
            return
        data = json.loads(manager._state_path.read_text()).get("ownership_journal", {})
    except (OSError, ValueError, AttributeError):
        return
    if (
        not isinstance(data, dict)
        or data.get("version") != 1
        or not data.get("boot_id")
        or data["boot_id"] != boot_id()
    ):
        return
    saved = data.get("identities", {})
    if not isinstance(saved, dict):
        return

    restored_units = _restore_passive_goals(manager, data, saved)
    if restored_units is None:
        return
    managed, admin = data.get("managed", []), data.get("admin", [])
    if isinstance(managed, list):
        manager._managed_units.update(unit for unit in managed if isinstance(unit, str) and unit in restored_units)
    _restore_admin_units(manager, admin, saved)
    domains = data.get("domains", {})
    if isinstance(domains, dict):
        manager._service_domains.update(
            {
                unit: domain
                for unit, domain in domains.items()
                if unit in manager._admin_units and isinstance(domain, str)
            }
        )
