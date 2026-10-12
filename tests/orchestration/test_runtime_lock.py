from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from test_task_lifecycle import World

from common import runtime_lock, systemd_ctrl


def test_runtime_lock_serializes_separate_file_descriptors(tmp_path):
    path = tmp_path / "state.lock"
    with runtime_lock.exclusive(path):
        with pytest.raises(TimeoutError):
            with runtime_lock.exclusive(path, timeout_s=0):
                raise AssertionError("a concurrent process acquired the task lock")
    with runtime_lock.exclusive(path, timeout_s=0):
        assert path.is_file()


def test_symlink_lock_fails_closed_without_service_actions(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    os.symlink(tmp_path / "other", tmp_path / "state.lock")
    result = manager.set_feature("s2_camera_preview", True)
    assert result["error"] == "orchestration_lock_unavailable" and not world.actions


def test_nested_task_and_recovery_transaction_reuses_lock(tmp_path):
    manager = World().manager(tmp_path)
    with manager.transaction():
        with manager.transaction():
            assert manager._transaction_depth == 1
    assert manager._transaction_depth == 0


def test_systemd_mutation_invalidates_snapshot_after_completion(monkeypatch, tmp_path):
    events = []
    backend = tmp_path / "backend"
    backend.write_text("")
    backend.chmod(0o755)
    monkeypatch.setattr(systemd_ctrl, "SERVICE_CTL", backend)
    monkeypatch.setattr(systemd_ctrl, "invalidate_snapshot", lambda: events.append("invalidate"))
    monkeypatch.setattr(
        systemd_ctrl.subprocess,
        "run",
        lambda *args, **kwargs: events.append("action") or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    assert systemd_ctrl.run_unit_action("camera-capture@raw.service", "start").ok
    assert events == ["invalidate", "action", "invalidate"]
