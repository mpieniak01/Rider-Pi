from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from common import systemd_snapshot
from common.service_catalog import UNIT_CATALOG
from services.api_core import resource_diag


def test_systemd_batch_cache_and_invalidate(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        text = "\n\n".join(
            f"Id={unit}\nLoadState=loaded\nActiveState=inactive\nSubState=dead\nUnitFileState=disabled\nMainPID=0"
            for unit in UNIT_CATALOG
        )
        return SimpleNamespace(stdout=text, stderr="", returncode=0)

    monkeypatch.setattr(systemd_snapshot.subprocess, "run", fake_run)
    systemd_snapshot.invalidate()
    first = systemd_snapshot.snapshot()
    second = systemd_snapshot.snapshot()
    assert len(calls) == 1 and set(first) == set(second) == set(UNIT_CATALOG)
    assert len(calls[0]) > len(UNIT_CATALOG)
    systemd_snapshot.invalidate()
    systemd_snapshot.snapshot()
    assert len(calls) == 2


def test_missing_unit_is_not_installed_despite_inactive(monkeypatch):
    output = "Id=rider-tracker.target\nLoadState=not-found\nActiveState=inactive\nSubState=dead"
    monkeypatch.setattr(
        systemd_snapshot.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=output, stderr="", returncode=1)
    )
    row = systemd_snapshot.snapshot(("rider-tracker.target",), force=True)["rider-tracker.target"]
    assert row["installed"] is False and row["load"] == "not-found"


def test_failed_read_retains_age_but_is_stale_unknown(monkeypatch):
    previous = {"unit": "rider-api.service", "observed_at": 1.0, "active": "active", "installed": True}
    monkeypatch.setattr(systemd_snapshot, "_CACHE", {"rider-api.service": previous})

    def failed(*args, **kwargs):
        raise OSError("manager unavailable")

    monkeypatch.setattr(systemd_snapshot.subprocess, "run", failed)
    row = systemd_snapshot.snapshot(("rider-api.service",), force=True)["rider-api.service"]
    assert row["observed_at"] == 1.0 and row["stale"] and not row["installed"]
    assert row["error"] == "manager unavailable"


@pytest.mark.parametrize("paths,error,expected", [([], False, "unavailable"), (["/dev/video0"], True, "unknown")])
def test_unknown_or_absent_resource_is_never_free(monkeypatch, paths, error, expected):
    monkeypatch.setattr(resource_diag, "_existing_paths", lambda patterns: paths)

    def observe(_paths):
        if error:
            raise RuntimeError("permission denied")
        return []

    monkeypatch.setattr(resource_diag, "_run_lsof", observe)
    row = resource_diag.inspect("camera")
    assert row["state"] == expected and row["free"] is None


def test_camera_never_includes_spi_and_uart_has_exact_owner(monkeypatch):
    patterns = []

    def paths(value):
        patterns.extend(value)
        return ["/dev/video0"]

    monkeypatch.setattr(resource_diag, "_existing_paths", paths)
    monkeypatch.setattr(resource_diag, "_run_lsof", lambda paths: [])
    resource_diag.inspect("camera")
    assert patterns == ["/dev/video*"]
    assert resource_diag.RESOURCE_SPECS["uart"]["paths"] == ["/dev/ttyAMA0"]


def test_lsof_newline_nul_fields_keep_exact_pid_path(monkeypatch):
    output = "p123\0cpython\0Lpi\0n/dev/video0\0\np124\0cother\0Lpi\0n/dev/spidev0.0\0\n"
    monkeypatch.setattr(
        resource_diag.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=output, stderr="", returncode=0)
    )
    holders = resource_diag._run_lsof(["/dev/video0"])
    assert [holder.pid for holder in holders] == [123, 124]
    assert holders[0].paths == ["/dev/video0"]


def test_forced_release_requires_current_owners_and_exact_consent(monkeypatch):
    from services.api_core import features_api

    monkeypatch.setattr(features_api.feature_manager, "resource_consumers", lambda: {})
    monkeypatch.setattr(
        resource_diag, "inspect", lambda _: {"state": "busy", "holders": [{"pid": 123, "service": "unmanaged.service"}]}
    )
    calls = []
    monkeypatch.setattr(resource_diag, "_call_release", lambda cmd: calls.append(cmd) or {"ok": True})
    assert not resource_diag.release("camera", limit_pids=[123])["ok"]
    assert not resource_diag.release("camera", limit_pids=[999], force=True, operator_consent=True)["ok"]
    assert calls == []
    assert resource_diag.release("camera", limit_pids=[123], force=True, operator_consent=True)["ok"]
    assert calls == [["sudo", "-n", "kill", "-TERM", "--", "123"]]


@pytest.mark.parametrize("resource", ["uart", "lcd"])
def test_uart_and_lcd_are_protected_from_forced_release(monkeypatch, resource):
    monkeypatch.setattr(resource_diag, "inspect", lambda _: {"state": "free", "holders": []})
    result = resource_diag.release(resource, limit_pids=[123], force=True, operator_consent=True)
    assert result["error"] == "protected_resource"


def test_task_consumers_block_forced_release(monkeypatch):
    from services.api_core import features_api

    monkeypatch.setattr(features_api.feature_manager, "resource_consumers", lambda: {"camera": ["s6_tracker_module"]})
    monkeypatch.setattr(
        resource_diag,
        "inspect",
        lambda _: {"state": "busy", "holders": [{"pid": 123, "service": "camera-capture@raw.service"}]},
    )
    result = resource_diag.release("camera", limit_pids=[123], force=True, operator_consent=True)
    assert result["error"] == "ownership_unknown_or_in_use"


def test_reconciliation_plan_is_complete_readonly_and_idempotent(tmp_path):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("systemd_reconcile", root / "scripts/systemd_reconcile.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = module.plan(root, tmp_path)
    assert all(row["source_exists"] for row in rows)
    names = {row["unit"] for row in rows}
    assert {"rider-tracker.target", "rider-obstacle.target", "rider-ai-provider.target"} <= names
    assert not list(tmp_path.iterdir())
    first = rows[0]
    (tmp_path / first["unit"]).symlink_to(first["source"])
    assert module.plan(root, tmp_path)[0]["operation"] == "keep"
    with pytest.raises(ValueError, match="root"):
        module.apply(rows, destination=tmp_path)


def test_reconcile_apply_and_rollback_are_reversible_without_process_actions(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("systemd_reconcile", root / "scripts/systemd_reconcile.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DESTINATION", tmp_path)
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    calls = []
    monkeypatch.setattr(module, "_systemctl", lambda *args: calls.append(args))
    old = tmp_path / "rider-api.service"
    old.write_text("previous unit")
    rows = module.plan(root, tmp_path)
    backup = module.apply(rows, destination=tmp_path)
    assert old.is_symlink()
    assert (backup / "rider-api.service").read_text() == "previous unit"
    assert calls == [("daemon-reload",)]
    module.rollback(backup)
    assert old.read_text() == "previous unit" and not old.is_symlink()
    assert not (tmp_path / "rider-tracker.target").exists()
    assert calls == [("daemon-reload",), ("daemon-reload",)]


def test_reconcile_rollback_refuses_changed_unit(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("systemd_reconcile", root / "scripts/systemd_reconcile.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DESTINATION", tmp_path)
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module, "_systemctl", lambda *args: None)
    backup = module.apply(module.plan(root, tmp_path), destination=tmp_path)
    changed = tmp_path / "rider-api.service"
    changed.unlink()
    changed.write_text("operator edit")
    with pytest.raises(ValueError, match="changed since migration"):
        module.rollback(backup)
    assert changed.read_text() == "operator edit"
