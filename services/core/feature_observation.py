"""Bounded systemd reads for one serialized task preparation, without actuation."""

from __future__ import annotations

import subprocess
import time

from common import systemd_snapshot
from common.service_catalog import UNIT_CATALOG


def read_units(units: tuple[str, ...], *, timeout: float) -> dict[str, dict]:
    """Reuse the canonical status contract, querying only the transaction members."""
    if not units or set(units) - set(UNIT_CATALOG):
        raise ValueError("unit outside canonical catalog")
    observed_at = time.time()
    values, error = {}, None
    try:
        result = subprocess.run(
            ["systemctl", "show", *units, "--no-page", f"--property={systemd_snapshot.PROPERTIES}"],
            capture_output=True,
            text=True,
            timeout=max(0.01, min(4.0, timeout)),
            check=False,
        )
        values = systemd_snapshot.parse_show(result.stdout)
        if result.returncode and not values:
            error = result.stderr.strip() or "systemd observation failed"
    except (OSError, subprocess.SubprocessError) as exc:
        error = str(exc)
    return {
        unit: systemd_snapshot._normalize(
            unit,
            values.get(unit, {}),
            observed_at,
            error or ("unit observation missing" if unit not in values else None),
        )
        for unit in units
    }
