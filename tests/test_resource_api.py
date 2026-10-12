from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

from services import api_server
from services.api_core import resource_diag, services_api


@pytest.fixture()
def client(monkeypatch) -> Any:
    monkeypatch.setattr(
        services_api, "_manager", lambda: SimpleNamespace(resource_consumers=lambda: {}, transaction=nullcontext)
    )
    with api_server.app.test_client() as test_client:
        yield test_client


def test_resource_status_endpoint(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    monkeypatch.setattr(resource_diag, "available_resources", lambda: ["mic", "speaker", "camera"])
    monkeypatch.setattr(resource_diag, "inspect", lambda name: {"resource": name, "holders": [], "free": True})

    resp = client.get("/api/resource/mic")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["resource"] == "mic"
    assert data["free"] is True


@pytest.mark.parametrize('released', [True, False])
def test_resource_release_endpoint(monkeypatch: pytest.MonkeyPatch, client: Any, released: bool) -> None:
    monkeypatch.setattr(resource_diag, "available_resources", lambda: ["mic"])

    called: dict[str, Any] = {}

    def fake_release(name: str, limit_pids: list[int], **kwargs):
        called["name"] = name
        called["pids"] = limit_pids
        called["consent"] = kwargs
        return {
            "ok": released,
            "released": released,
            "pending": not released,
            "signal_sent": True,
            "after": {"free": released, "state": "free" if released else "busy"},
        }

    monkeypatch.setattr(resource_diag, "release", fake_release)

    resp = client.post(
        "/api/resource/mic", json={"action": "release", "pids": [123, 124], "force": True, "operator_consent": True}
    )
    assert resp.status_code == (200 if released else 202)
    assert resp.get_json()['released'] is released
    assert resp.get_json()['pending'] is not released
    assert called == {"name": "mic", "pids": [123, 124], "consent": {"force": True, "operator_consent": True}}


@pytest.mark.parametrize('released', [True, False])
def test_resource_stop_endpoint(monkeypatch: pytest.MonkeyPatch, client: Any, released: bool) -> None:
    monkeypatch.setattr(resource_diag, "available_resources", lambda: ["mic"])
    observations = iter(
        [
            {"state": "busy", "free": False, "holders": [{"service": "rider-voice.service"}]},
            {
                "state": "free" if released else "busy",
                "free": released,
                "holders": [] if released else [{"service": "rider-voice.service"}],
            },
        ]
    )
    monkeypatch.setattr(resource_diag, "inspect", lambda name: next(observations))

    called: list[str] = []

    def fake_run_step(unit: str, action: str) -> dict[str, Any]:
        called.append(f"{unit}:{action}")
        return {"unit": unit, "action": action, "ok": True}

    monkeypatch.setattr(
        services_api,
        "_manager",
        lambda: SimpleNamespace(resource_consumers=lambda: {}, service_action=fake_run_step, transaction=nullcontext),
    )

    resp = client.post("/api/resource/mic", json={"action": "stop"})
    assert resp.status_code == (200 if released else 202)
    assert resp.get_json()['released'] is released
    assert called == ["rider-voice.service:stop"]


@pytest.mark.parametrize("action,active", [("on", "active"), ("off", "inactive")])
def test_lcd_resource_operation_observed(action, active):
    from services.api_core.operation_result import result_for

    with api_server.app.test_request_context("/api/resource/lcd", method="POST"):
        from flask import request

        request.view_args = {"name": "lcd"}
        operation = result_for(
            "/api/resource/<name>", {"ok": True, "status": {"active": active}}, 200, {"action": action}
        )
    assert operation["action"] == action
    assert operation["status"] == "executed"
    assert operation["confirmed"] is True
    assert operation["ack_kind"] == "systemd_observed"


@pytest.mark.parametrize("running,sink,confirmed", [(True, "lcd", True), (False, "lcd", False), (True, "png", False)])
def test_lcd_already_on_requires_observed_lcd_runtime(running, sink, confirmed):
    from services.api_core.operation_result import result_for

    with api_server.app.test_request_context("/api/resource/lcd", method="POST"):
        from flask import request

        request.view_args = {"name": "lcd"}
        operation = result_for(
            "/api/resource/<name>",
            {"ok": True, "idempotent": True, "face": {"running": running, "sink": sink}},
            200,
            {"action": "on"},
        )
    assert operation["confirmed"] is confirmed
    assert operation["status"] == ("executed" if confirmed else "unknown")


@pytest.mark.parametrize("action,service_action,active", [("on", "restart", "active"), ("off", "stop", "inactive")])
def test_lcd_canonical_http_confirmed(monkeypatch, client, action, service_action, active):
    from services.api_core import face_anim, hardware_api

    calls = []

    def run(unit, verb):
        calls.append((unit, verb))
        return {"ok": True, "unit": unit, "status": {"active": active}}

    monkeypatch.setattr(hardware_api, "manager", lambda: SimpleNamespace(transaction=nullcontext, service_action=run))
    monkeypatch.setattr(face_anim, "get_state", lambda: {"state": {"running": False}})
    monkeypatch.setattr(face_anim, "stop", lambda: {"state": {"running": False, "playing": False}})
    response = client.post(
        "/api/resource/lcd",
        json={"action": action},
        headers={"Accept": "application/vnd.rider.api+json;version=1"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["operation"]["status"] == "executed"
    assert body["operation"]["action"] == action
    assert calls == [("lcd-renderer.service", service_action)]
