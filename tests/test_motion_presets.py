"""Device presets use isolated files and fake executor only."""

import pytest
from flask import Flask
from motion_fakes import executor as executor
from test_manual_settings import operator_arm

from apps.motion import manual_settings as settings
from services import calibration_api


def test_named_profiles_roundtrip_restore_all_fields(executor):
    current = settings.read()
    gentle = settings.manage_profile(
        {"action": "create", "name": "Delikatnie — biurko"},
        current["revision"],
        patch={"linear_deceleration": 5},
        directions={"forward": {"speed": 0.15}, "left": {"speed": 0.2}},
    )
    key = gentle["active_profile"]
    assert settings.read() == gentle
    changed = settings.update({}, gentle["revision"], directions={"backward": {"speed": 0.5}})
    assert settings.profile_modified(changed)
    fast = settings.manage_profile({"action": "create", "name": "Podłoga"}, changed["revision"])
    restored = settings.manage_profile({"action": "apply", "id": key}, fast["revision"])
    assert restored["values"] == gentle["values"]
    assert restored["directions"] == gentle["directions"]
    assert not settings.profile_modified(restored)
    assert len(restored["profiles"]) == 2


def test_update_rename_delete_preserves_current_settings(executor):
    created = settings.manage_profile({"action": "create", "name": "A"}, settings.read()["revision"])
    key = created["active_profile"]
    saved = settings.manage_profile(
        {"action": "save", "id": key, "name": "Biurko"}, created["revision"], directions={"forward": {"speed": 0.3}}
    )
    assert saved["profiles"][key]["name"] == "Biurko"
    assert saved["profiles"][key]["directions"]["forward"]["speed"] == 0.3
    deleted = settings.manage_profile({"action": "delete", "id": key}, saved["revision"])
    assert deleted["active_profile"] is None and deleted["profiles"] == {}
    assert deleted["directions"] == saved["directions"]


@pytest.mark.parametrize(
    "operation",
    [
        {"action": "create", "name": ""},
        {"action": "create", "name": "x" * 61},
        {"action": "create", "name": "Bad\nname"},
        {"action": "apply", "id": "missing"},
        {"action": "unknown"},
    ],
)
def test_invalid_operation_is_atomic(executor, operation):
    before = settings.read()
    with pytest.raises(ValueError):
        settings.manage_profile(operation, before["revision"])
    assert settings.read() == before


def test_stale_writer_cannot_override_profile(executor):
    row = settings.read()
    settings.manage_profile({"action": "create", "name": "A"}, row["revision"])
    with pytest.raises(ValueError, match="conflict"):
        settings.manage_profile({"action": "create", "name": "B"}, row["revision"])
    assert len(settings.read()["profiles"]) == 1


def test_api_profile_creation_armed_idle_never_actuates(executor, monkeypatch):
    instance, clock = executor
    operator_arm(instance)
    generation = instance.gate.generation
    before = list(instance.adapter.calls)
    monkeypatch.setattr(calibration_api, "read_status", instance.snapshot)
    monkeypatch.setattr(calibration_api, "wall_clock", clock)
    monkeypatch.setattr(calibration_api, "_publish", lambda *a: pytest.fail("profile must not publish commands"))
    app = Flask(__name__)
    app.add_url_rule("/controls", view_func=calibration_api.controls, methods=["POST"])
    response = app.test_client().post(
        "/controls",
        json={"revision": settings.read()["revision"], "values": {}, "profile": {"action": "create", "name": "Biurko"}},
    )
    assert response.status_code == 200
    assert response.json["profiles"][response.json["active_profile"]]["name"] == "Biurko"
    assert instance.adapter.calls == before
    assert instance.gate.state == "ARMED" and instance.gate.generation == generation


def test_profiles_cannot_exceed_full_command_range(executor):
    row = settings.read()
    with pytest.raises(ValueError):
        settings.manage_profile({"action": "create", "name": "Wyścig"}, row["revision"], patch={"speed_limit": 1.01})
    assert settings.read() == row


def test_negotiated_http_confirms_persisted_profile(executor, monkeypatch):
    from services.api_core.http_contract import install

    instance, clock = executor
    monkeypatch.setattr(calibration_api, "read_status", instance.snapshot)
    monkeypatch.setattr(calibration_api, "wall_clock", clock)
    app = Flask(__name__)
    install(app, after_request=True)
    app.add_url_rule("/api/calibration/controls", view_func=calibration_api.controls, methods=["GET", "POST"])
    response = app.test_client().post(
        "/api/calibration/controls",
        headers={"Accept": "application/vnd.rider.api+json;version=1"},
        json={"revision": settings.read()["revision"], "values": {}, "profile": {"action": "create", "name": "Test"}},
    )
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["operation"]["ack_kind"] == "configuration_persisted"
    assert response.json["operation"]["actuation"] is False
