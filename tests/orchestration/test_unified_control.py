"""API/direct CLI share handlers, journal and transitions. No real I/O."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from flask import Flask

from common.api_client import ACCEPT
from common.local_api_client import LocalAPIClient
from services.api_core import features_api, services_api
from services.api_core.http_contract import install
from services.core import camera_state, goal_journal
from tests.orchestration.test_task_lifecycle import World


def observed_world(tmp_path):
    world = World()
    original = world.status
    identities = {}

    def status(unit):
        return {**original(unit), "pid": identities.get(unit, 100), "since": "same-start", "stale": False}

    world.status = status
    return world, world.manager(tmp_path), identities


def test_passive_goal_restores_without_starting_services(tmp_path):
    world, manager, identities = observed_world(tmp_path)
    assert manager.set_feature("s2_camera_preview", True)["ok"]
    world.actions.clear()
    restarted = world.manager(tmp_path)
    rows = restarted.describe_features()
    assert next(row for row in rows if row["name"] == "s2_camera_preview")["requested"]
    assert not world.actions
    assert restarted.set_feature("s2_camera_preview", False)["ok"]
    assert not world.active.intersection({"camera-capture@raw.service", "frame-distributor.service"})


@pytest.mark.parametrize("change", ["boot", "pid", "since", "malformed"])
def test_unverified_journal_never_takes_ownership(tmp_path, monkeypatch, change):
    world, manager, identities = observed_world(tmp_path)
    assert manager.set_feature("s2_camera_preview", True)["ok"]
    if change == "boot":
        monkeypatch.setattr(goal_journal, "boot_id", lambda: "different-boot")
    elif change == "pid":
        identities["camera-capture@raw.service"] = 999
    else:
        data = json.loads(manager._state_path.read_text())
        if change == "since":
            data["ownership_journal"]["identities"]["camera-capture@raw.service"]["since"] = "different-start"
        else:
            data["ownership_journal"]["admin"] = [{}]
        manager._state_path.write_text(json.dumps(data))
    world.actions.clear()
    rows = world.manager(tmp_path).describe_features()
    if change != "malformed":
        assert not next(row for row in rows if row["name"] == "s2_camera_preview")["requested"]
    assert not world.actions


def test_moving_goals_never_restored(tmp_path):
    world, manager, _ = observed_world(tmp_path)
    assert manager.set_feature("face_tracking", True)["ok"]
    world.actions.clear()
    restarted = world.manager(tmp_path)
    assert not next(row for row in restarted.describe_features() if row["name"] == "s3_follow_me_face")["requested"]
    assert not world.actions


def test_http_and_direct_transport_execute_same_handlers(tmp_path, monkeypatch):
    world, manager, _ = observed_world(tmp_path)
    monkeypatch.setattr(features_api, "feature_manager", manager)
    app = Flask("http-projection")
    app.add_url_rule("/api/logic/feature/<name>", view_func=features_api.feature_handler, methods=["POST"])
    install(app, after_request=True)
    direct = LocalAPIClient()
    response = direct.request("/api/logic/feature/s2_camera_preview", "POST", {"enabled": True})
    assert response["ok"]
    assert response["meta"]["contract_id"] == "rider.tasks"
    # HTTP sees the same ownership established by the local handler.
    response = app.test_client().post(
        "/api/logic/feature/s2_camera_preview", json={"enabled": False}, headers={"Accept": ACCEPT}
    )
    assert response.status_code == 200
    assert response.json["ok"]
    assert not manager.resource_consumers().get("camera")


def test_direct_service_uses_same_manager(tmp_path, monkeypatch):
    world, manager, _ = observed_world(tmp_path)
    monkeypatch.setattr(features_api, "feature_manager", manager)
    response = LocalAPIClient().request("/svc/camera-capture@raw.service", "POST", {"action": "start"})
    assert response["ok"]
    assert world.actions == [("camera-capture@raw.service", "start")]


@pytest.mark.parametrize(
    "active,fresh,free,expected",
    [
        (False, False, None, None),
        (False, False, True, False),
        (False, True, True, False),
        (True, False, True, True),
        (False, True, None, None),
    ],
)
def test_camera_activity_never_conflates_frame_and_process(active, fresh, free, expected):
    row = {"active": "active" if active else "inactive"}
    data = camera_state.snapshot(
        heartbeat={"ts": 99 if fresh else 1},
        now=100,
        status_fn=lambda unit: row,
        owners={"free": free, "holders": []},
    )
    assert data["on"] is expected
    assert data["data_fresh"] is fresh
    assert data["service_running"] is active


def test_stop_external_goal_never_falsely_claims_stopped(tmp_path):
    world, manager, _ = observed_world(tmp_path)
    world.active.add("camera-capture@raw.service")
    result = manager.set_feature("s2_camera_preview", False)
    assert result["error"] == "external_services_running"
    assert not world.actions


def test_stop_unrequested_processor_preserves_camera_owned_by_other_goal(tmp_path):
    world, manager, _ = observed_world(tmp_path)
    assert manager.set_feature("s2_camera_preview", True)["ok"]
    world.actions.clear()
    assert manager.set_feature("s7_obstacle_module", False)["ok"]
    assert "camera-capture@raw.service" in world.active
    assert not world.actions


def test_local_processor_is_independent_of_remote_executor(tmp_path, monkeypatch):
    from common.service_catalog import DEFAULT_REGISTRY, task_availability
    from services import compute_config

    monkeypatch.setattr(compute_config, "snapshot", lambda: {"selected_executor": "venom"})
    world, manager, _ = observed_world(tmp_path)
    assert manager.set_feature("s2_camera_preview", True)["ok"]
    assert task_availability(DEFAULT_REGISTRY["s7_obstacle_module"], {"provider": "local"})["start_available"]
    assert manager.set_feature("s7_obstacle_module", True, options={"provider": "local"})["ok"]
    assert "rider-vision.service" in world.active
    assert "rider-obstacle.service" in world.active
    assert "rider-vision-offload.service" not in world.active
    world.actions.clear()
    assert manager.set_feature("s7_obstacle_module", False)["ok"]
    assert "camera-capture@raw.service" in world.active
    assert not any(action == ("camera-capture@raw.service", "stop") for action in world.actions)
    assert not any(action[0] == "control" for action in world.actions)
    assert (
        manager.set_feature("s7_obstacle_module", True, options={"provider": "pc"})["error"]
        == "compute_use_remote_goal"
    )
    assert manager.set_feature("s5_voice", True)["error"] == "compute_use_remote_goal"
