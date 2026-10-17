"""Explicit source OFF after API ownership loss; no hardware or BUS calls."""

import json
import os
import time

import pytest
from test_camera_pipeline import CAPS, Manager as BaseManager, command, isolated_paths as isolated_paths

from services import camera_pipeline as domain, camera_pipeline_store as store


class Manager(BaseManager):
    def _status(self, unit):
        return {**super()._status(unit), "load": "loaded", "pid": os.getpid() if unit in self.units else 0}

    def service_action(self, unit, action):
        self.calls.append((unit, action))
        assert action == "stop"
        self.units.discard(unit)
        (store.runtime_path() / "status.json").write_text(json.dumps({"state": "stopped"}))
        return {"ok": True}


@pytest.fixture
def orphan(tmp_path, monkeypatch):
    manager = Manager()
    manager.units.add(manager.PREVIEW_UNIT)
    store.write({"contract_version": 1, "revision": 1, "profile": dict(store.DEFAULT_PROFILE)})
    runtime = store.runtime_path()
    runtime.mkdir()
    (runtime / "status.json").write_text(
        json.dumps(
            {
                "state": "active",
                "pid": os.getpid(),
                "pipeline_revision": 1,
                "active_profile": dict(store.DEFAULT_PROFILE),
                "camera_session": "source-1",
                "observed_monotonic_ns": time.monotonic_ns(),
            }
        )
    )
    proc = tmp_path / "proc"
    group = proc / str(os.getpid()) / "cgroup"
    group.parent.mkdir(parents=True)
    group.write_text("0::/system.slice/system-camera\\x2dcapture.slice/camera-capture@raw.service\n")
    monkeypatch.setattr(domain, "PROC_ROOT", proc, raising=False)
    return domain.CameraPipeline(manager, capability_fn=lambda: CAPS), manager, group


def test_explicit_off_releases_proven_pipeline_without_requested_goals(orphan):
    instance, manager, _ = orphan
    body = command("stop")
    result, status = instance.execute(body)
    assert status == 200, result
    assert result["state"] == "stopped" and result["consumers"] == []
    assert manager.calls == [(manager.PREVIEW_UNIT, "stop")]
    assert instance.execute(body) == (result, status)
    assert manager.calls == [(manager.PREVIEW_UNIT, "stop")]


@pytest.mark.parametrize(
    "failure", ["unknown", "suffix", "stale", "revision", "profile", "legacy", "foreign", "multiple", "observation"]
)
def test_orphan_proof_failure_does_not_stop_any_unit(orphan, failure):
    instance, manager, group = orphan
    path = store.runtime_path() / "status.json"
    row = json.loads(path.read_text())
    if failure == "unknown":
        group.write_text("0::/user.slice/unrelated.service\n")
    elif failure == "suffix":
        group.write_text("0::/system.slice/not-camera-capture@raw.service\n")
    elif failure == "stale":
        row["observed_monotonic_ns"] -= 10_000_000_000
    elif failure == "revision":
        row["pipeline_revision"] = 2
    elif failure == "profile":
        row["active_profile"] = dict(store.DEFAULT_PROFILE, local_engine="ssd")
    elif failure == "legacy":
        store.config_path().unlink()
    elif failure == "foreign":
        manager.consumers = ["s3_follow_me_face"]
    elif failure == "multiple":
        manager.units.add("camera-capture@edge.service")
    elif failure == "observation":
        manager._status = lambda _: {"load": "loaded", "active": "active", "pid": os.getpid(), "stale": True}
    path.write_text(json.dumps(row))
    response, code = instance.execute(command("stop"))
    assert code == 409, response
    assert manager.calls == [] and manager.PREVIEW_UNIT in manager.units


def test_profile_change_cannot_adopt_or_stop_orphan(orphan):
    instance, manager, _ = orphan
    response, code = instance.execute(command("configure", profile=dict(store.DEFAULT_PROFILE, local_engine="ssd")))
    assert code == 409 and response["error"] == "camera_pipeline_camera_not_released"
    assert manager.calls == [] and store.snapshot()["profile"] == store.DEFAULT_PROFILE


@pytest.mark.parametrize("ack", [False, True])
def test_stop_error_or_positive_ack_without_release_is_not_success(orphan, ack):
    instance, manager, _ = orphan
    manager.service_action = lambda *_: {"ok": ack, "error": None if ack else "backend_failed"}
    response, code = instance.execute(command("stop"))
    assert code in {409, 503} and response["ok"] is False
    assert manager.PREVIEW_UNIT in manager.units


def test_manual_motion_still_blocks_orphan_release(orphan):
    instance, manager, _ = orphan
    manager.safety.update(moving=True, output={"lx": 0.1})
    response, code = instance.execute(command("stop"))
    assert code == 409 and response["error"] == "camera_pipeline_motion_busy"
    assert manager.calls == []


@pytest.mark.parametrize("unit", domain.CAPTURE_UNITS)
@pytest.mark.parametrize("hierarchy", ["0::", "1:name=systemd:"])
def test_known_capture_variants_and_cgroup_versions(orphan, unit, hierarchy):
    instance, manager, group = orphan
    manager.units = {unit}
    group.write_text(hierarchy + "/system.slice/" + unit + "\n")
    response, code = instance.execute(command("stop"))
    assert code == 200, response
    assert manager.calls == [(unit, "stop")]


@pytest.mark.parametrize(
    "status",
    [
        {"load": "not-found"},
        {"active": "activating"},
        {"pid": 0},
        {"pid": True},
        {"error": "unavailable"},
    ],
)
def test_invalid_service_identity_is_not_released(orphan, status):
    instance, manager, _ = orphan
    original = manager._status
    manager._status = lambda unit: {**original(unit), **status}
    response, code = instance.execute(command("stop"))
    assert code == 409 and not response["ok"]
    assert manager.calls == []


def test_missing_cgroup_does_not_release(orphan):
    instance, manager, group = orphan
    group.unlink()
    assert instance.execute(command("stop"))[1] == 409
    assert manager.calls == []


def test_live_producer_after_service_stop_is_not_acknowledged_as_released(orphan):
    instance, manager, _ = orphan

    def stop(unit, action):
        manager.units.discard(unit)
        return {"ok": True}

    manager.service_action = stop
    response, code = instance.execute(command("stop"))
    assert code == 409 and response["error"] == "camera_pipeline_camera_not_released"


def test_stale_revision_does_not_release_proven_orphan(orphan):
    instance, manager, _ = orphan
    response, code = instance.execute(command("stop", revision=2))
    assert code == 409 and response["error"] == "camera_pipeline_revision_conflict"
    assert manager.calls == []
