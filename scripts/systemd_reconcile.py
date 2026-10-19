#!/usr/bin/env python3
"""Plan/link catalog units with backup; no process start/stop or network changes."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from common.service_catalog import BOOT_UNITS, UNIT_CATALOG

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = Path("/etc/systemd/system")
MANIFEST_FILENAME = "manifest.json"


def sources(root: Path = ROOT) -> dict[str, Path]:
    units = {unit.split("@", 1)[0] + "@.service" if "@" in unit else unit for unit in UNIT_CATALOG}
    return {unit: root / "systemd" / unit for unit in sorted(units)}


def plan(root: Path = ROOT, destination: Path = DESTINATION) -> list[dict]:
    rows = []
    for unit, source in sources(root).items():
        target = destination / unit
        same = target.is_symlink() and target.resolve() == source.resolve()
        rows.append(
            {
                "unit": unit,
                "source": str(source),
                "installed_path": str(target),
                "source_exists": source.is_file(),
                "operation": "keep" if same else "link",
                "previous": os.readlink(target) if target.is_symlink() else "file" if target.exists() else None,
            }
        )
    return rows


def _systemctl(*args: str) -> None:
    subprocess.run(["systemctl", *args], check=True, timeout=20)


def _save_manifest(backup, manifest):
    (backup / MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _backup_units(rows, backup):
    for row in rows:
        target = Path(row["installed_path"])
        if target.exists() or target.is_symlink():
            shutil.copy2(target, backup / row["unit"], follow_symlinks=False)


def _link_units(rows, backup, manifest):
    for row in rows:
        target = Path(row["installed_path"])
        if row["operation"] != "keep":
            temporary = target.with_name(target.name + ".rider-new")
            temporary.symlink_to(row["source"])
            temporary.replace(target)
            manifest["units"].append(row)
            _save_manifest(backup, manifest)


def _consolidate_boot(rows, backup, manifest):
    baseline = set(BOOT_UNITS)
    for unit in sorted(UNIT_CATALOG):
        proc = subprocess.run(["systemctl", "is-enabled", unit], capture_output=True, text=True, check=False, timeout=4)
        previous = proc.stdout.strip()
        desired = "enable" if unit in baseline else "disable"
        if (desired == "enable" and previous == "enabled") or (desired == "disable" and previous != "enabled"):
            continue
        manifest["boot_changes"].append({"unit": unit, "previous": previous, "action": desired})
        _save_manifest(backup, manifest)
        _systemctl("--no-reload", desired, unit)
    # disable may remove a linked unit file; restore canonical availability.
    for row in rows:
        target = Path(row["installed_path"])
        if not target.exists() and not target.is_symlink():
            target.symlink_to(row["source"])


def apply(rows: list[dict], *, destination: Path = DESTINATION, consolidate_boot: bool = False) -> Path:
    if destination.resolve() != DESTINATION or os.geteuid() != 0:
        raise ValueError("apply requires root and /etc/systemd/system")
    if any(not row["source_exists"] for row in rows):
        raise ValueError("catalog source missing; nothing applied")
    backup = destination / ("_rider_catalog_" + str(time.time_ns()))
    backup.mkdir(mode=0o700)
    manifest = {"units": [], "boot_changes": []}
    _backup_units(rows, backup)
    _save_manifest(backup, manifest)
    _link_units(rows, backup, manifest)
    # Boot policy is a separate explicit migration. Never --now/start/restart.
    if consolidate_boot:
        _consolidate_boot(rows, backup, manifest)
    _save_manifest(backup, manifest)
    _systemctl("daemon-reload")
    return backup


def rollback(backup: Path) -> None:
    resolved = backup.resolve()
    if os.geteuid() != 0 or resolved.parent != DESTINATION or not resolved.name.startswith("_rider_catalog_"):
        raise ValueError("rollback requires root and a catalog backup in /etc/systemd/system")
    manifest = json.loads((resolved / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    for row in manifest["units"]:
        target = DESTINATION / row["unit"]
        if not target.is_symlink() or os.readlink(target) != row["source"]:
            raise ValueError(f"unit changed since migration: {row['unit']}")
    for row in manifest["units"]:
        target = DESTINATION / row["unit"]
        saved = resolved / row["unit"]
        target.unlink()
        if saved.is_symlink() or saved.exists():
            shutil.copy2(saved, target, follow_symlinks=False)
    for change in reversed(manifest["boot_changes"]):
        action = "enable" if change["previous"] == "enabled" else "disable"
        _systemctl("--no-reload", action, change["unit"])
    _systemctl("daemon-reload")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="link catalog units; requires root; never starts a task")
    parser.add_argument(
        "--consolidate-boot", action="store_true", help="explicitly migrate boot ownership; requires --apply"
    )
    parser.add_argument("--rollback", type=Path)
    parser.add_argument("--with-dev", action="store_true", help="compatibility: no legacy units are installed")
    args = parser.parse_args()
    if args.rollback:
        if args.apply or args.consolidate_boot:
            parser.error("rollback cannot be combined with apply")
        rollback(args.rollback)
        return
    if args.consolidate_boot and not args.apply:
        parser.error("--consolidate-boot requires --apply")
    rows = plan()
    print(
        json.dumps(
            {
                "units": rows,
                "effects": ["link unit files", "daemon-reload"] if args.apply else [],
                "boot_migration": args.consolidate_boot,
                "starts_processes": False,
            },
            indent=2,
        )
    )
    if args.apply:
        print("Backup: " + str(apply(rows, consolidate_boot=args.consolidate_boot)))


if __name__ == "__main__":
    main()
