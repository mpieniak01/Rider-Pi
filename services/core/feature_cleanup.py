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
