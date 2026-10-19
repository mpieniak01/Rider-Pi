"""Exercise real persistence functions with isolated files and no device actions."""

from __future__ import annotations

import json
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from common import secure_files
from services import api_server
from services.core import device_control, goal_journal
from services.core.feature_state import FeatureStateMixin


@pytest.fixture(params=["led", "feature", "command"])
def persistence(request, tmp_path, monkeypatch):
    directory = tmp_path / "state"
    directory.mkdir(mode=0o750)
    path = directory / "state.json"
    kind = request.param
    warning = Mock()
    monkeypatch.setattr(api_server.app.logger, "warning", warning)
    monkeypatch.setattr(goal_journal, "boot_id", lambda: "fixture-boot")
    monkeypatch.setattr(goal_journal, "journal", lambda state: {"generation": "accepted-generation"})
    monkeypatch.setenv("RIDER_LED_STATE_PATH", str(path))
    monkeypatch.setattr(api_server, "GOOGLE_DATA_DIR", directory)
    monkeypatch.setattr(api_server, "LAST_COMMAND_FILE", path)

    def write(value="../payload-is-data"):
        if kind == "led":
            return device_control._save_led_generation(value, "heartbeat")
        if kind == "feature":
            state = SimpleNamespace(_state_path=path, state_snapshot=lambda: {"requested": value, "label": "żółw"})
            return FeatureStateMixin._persist_state(state)
        return api_server._save_command_cache(value, "fixture-command", {"text": value}, {"ok": True, "result": value})

    return SimpleNamespace(path=path, directory=directory, kind=kind, write=write, warning=warning)


def assert_private(persistence):
    assert stat.S_IMODE(persistence.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(persistence.directory.stat().st_mode) == 0o750
    assert not list(persistence.directory.glob(".rider-write-*"))


def assert_failure(persistence):
    if persistence.kind == "led":
        with pytest.raises(OSError):
            persistence.write()
    elif persistence.kind == "feature":
        assert persistence.write() is False
    else:
        assert persistence.write() is None
        persistence.warning.assert_called_once()


def test_json_contract_and_private_permissions(persistence):
    result = persistence.write()
    data = json.loads(persistence.path.read_text(encoding="utf-8"))
    if persistence.kind == "led":
        assert data == {
            "boot_id": "fixture-boot",
            "sessions": {"../payload-is-data": result},
            "defaults": {"../payload-is-data": "heartbeat"},
        }
        assert len(result) == 32
    elif persistence.kind == "feature":
        assert result is True
        assert data == {
            "requested": "../payload-is-data",
            "label": "żółw",
            "ownership_journal": {"generation": "accepted-generation"},
        }
    else:
        assert result is None
        assert data["device_id"] == "../payload-is-data"
        assert data["command"] == "fixture-command"
        assert data["params"] == {"text": "../payload-is-data"}
        assert data["ok"] is True and data["response"] == "../payload-is-data" and data["error"] is None
        assert isinstance(data["timestamp"], float)
    persistence.warning.assert_not_called()
    assert_private(persistence)
    assert list(persistence.directory.iterdir()) == [persistence.path]


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_old_temporary_and_final_links_cannot_overwrite_victim(persistence, link_kind):
    victim = persistence.directory.parent / "victim"
    victim.write_bytes(b"preserve unrelated file")
    old_temporary = persistence.path.with_suffix(".tmp")
    old_temporary.symlink_to(victim)
    if link_kind == "symlink":
        persistence.path.symlink_to(victim)
    else:
        os.link(victim, persistence.path)

    persistence.write()

    assert victim.read_bytes() == b"preserve unrelated file"
    assert old_temporary.is_symlink()
    assert not persistence.path.is_symlink()
    json.loads(persistence.path.read_text())
    assert persistence.path.stat().st_ino != victim.stat().st_ino
    assert_private(persistence)


@pytest.mark.parametrize("intermediate", [False, True])
def test_directory_symlink_is_rejected(persistence, intermediate):
    original = persistence.directory.with_name("original")
    persistence.directory.rename(original)
    if intermediate:
        persistence.directory.mkdir()
        parent = persistence.directory.parent
        pinned = parent.with_name(parent.name + "-pinned")
        parent.rename(pinned)
        parent.symlink_to(pinned, target_is_directory=True)
        original = pinned / "state"
    else:
        persistence.directory.symlink_to(original, target_is_directory=True)

    assert_failure(persistence)
    assert list(original.iterdir()) == []


def test_failed_publication_keeps_previous_state_and_cleans_temporary(persistence, monkeypatch):
    persistence.path.write_bytes(b'{"previous":true}')

    def fail(*args, **kwargs):
        raise OSError("simulated full filesystem")

    monkeypatch.setattr(secure_files.os, "replace", fail)
    assert_failure(persistence)
    assert persistence.path.read_bytes() == b'{"previous":true}'
    assert list(persistence.directory.iterdir()) == [persistence.path]


def test_concurrent_publications_use_independent_temporary_files(persistence, monkeypatch):
    barrier = threading.Barrier(8, timeout=10)
    real_replace = os.replace

    def synchronize(*args, **kwargs):
        barrier.wait()
        return real_replace(*args, **kwargs)

    monkeypatch.setattr(secure_files.os, "replace", synchronize)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(persistence.write, ["value-" + str(i) for i in range(8)]))
    if persistence.kind == "feature":
        assert all(results)
    persistence.warning.assert_not_called()
    data = json.loads(persistence.path.read_text())
    assert data
    assert_private(persistence)
    assert list(persistence.directory.iterdir()) == [persistence.path]
