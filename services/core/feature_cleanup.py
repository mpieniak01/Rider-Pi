"""Recognize empty navigation targets left behind by an exited producer."""

from common.service_catalog import PROTECTED_UNITS, task_units


def orphan_targets(manager, feature, external):
    """Never adopt live services or targets that can affect dependencies."""
    if not external or any(not unit.endswith(".target") for unit in external):
        return ()
    for unit in external:
        row = manager._status(unit)
        if (
            row.get("error")
            or row.get("stale")
            or row.get("load") != "loaded"
            or row.get("pid") != 0
            or row.get("wants") != []
            or row.get("requires") != []
        ):
            return ()
    consumers = manager._consumers()
    for unit in task_units(feature, {}):
        if unit.endswith(".target") or unit in PROTECTED_UNITS or consumers.get(unit):
            continue
        row = manager._status(unit)
        if (
            row.get("error")
            or row.get("stale")
            or row.get("load") != "loaded"
            or row.get("active") not in {"inactive", "failed"}
            or row.get("pid") != 0
        ):
            return ()
    return tuple(external)


def inactive_navigation_target(unit):
    """Privileged backend repeats proof before a non-actuating target stop."""
    producer = {
        "rider-venom-navigation.target": "rider-venom-navigation.service",
        "rider-venom-perception.target": "rider-venom-perception.service",
    }.get(unit)
    if producer is None:
        return False
    from services.core.feature_observation import read_units

    rows = read_units((unit, producer), timeout=1.0)
    target, process = rows[unit], rows[producer]
    return (
        target.get("load") == "loaded"
        and not target.get("error")
        and not target.get("stale")
        and target.get("pid") == 0
        and target.get("wants") == []
        and target.get("requires") == []
        and process.get("load") == "loaded"
        and not process.get("error")
        and not process.get("stale")
        and process.get("active") in {"inactive", "failed"}
        and process.get("pid") == 0
    )
