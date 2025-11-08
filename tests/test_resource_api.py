from __future__ import annotations

from typing import Any

import pytest

from services import api_server
from services.api_core import resource_diag, services_api


@pytest.fixture()
def client() -> Any:
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


def test_resource_release_endpoint(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    monkeypatch.setattr(resource_diag, "available_resources", lambda: ["mic"])

    called: dict[str, Any] = {}

    def fake_release(name: str, limit_pids: list[int]):
        called["name"] = name
        called["pids"] = limit_pids
        return {"ok": True}

    monkeypatch.setattr(resource_diag, "release", fake_release)

    resp = client.post("/api/resource/mic", json={"action": "release", "pids": [1, 2]})
    assert resp.status_code == 200
    assert called == {"name": "mic", "pids": [1, 2]}


def test_resource_stop_endpoint(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    monkeypatch.setattr(resource_diag, "available_resources", lambda: ["mic"])
    monkeypatch.setattr(resource_diag, "inspect", lambda name: {"holders": [{"service": "rider-voice.service"}]})

    called: list[str] = []

    def fake_run_step(unit: str, action: str) -> dict[str, Any]:
        called.append(f"{unit}:{action}")
        return {"unit": unit, "action": action, "ok": True}

    monkeypatch.setattr(services_api, "_run_step", fake_run_step)

    resp = client.post("/api/resource/mic", json={"action": "stop"})
    assert resp.status_code == 200
    assert called == ["rider-voice.service:stop"]
