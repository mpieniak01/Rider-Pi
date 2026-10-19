from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from flask import Flask

from common import systemd_snapshot
from services.api_core import features_api, services_dashboard_api
from services.api_core.service_meta import SERVICE_META


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setattr(services_dashboard_api, "get_wifi_state", lambda: {"status": "connected"})
    monkeypatch.setattr(features_api, "feature_manager", SimpleNamespace(unit_consumers=lambda _: []))
    monkeypatch.setattr(systemd_snapshot, "_CACHE", {})
    monkeypatch.setattr(systemd_snapshot, "_LAST_REFRESH", 0.0)
    app = Flask(__name__)
    app.register_blueprint(services_dashboard_api.bp)
    with app.test_client() as test_client:
        yield test_client


def _fake_output(unit: str, state: str) -> str:
    sub = "running" if state == "active" else ("failed" if state == "failed" else "dead")
    return "\n".join(
        [
            f"Id={unit}",
            "LoadState=loaded",
            "UnitFileState=disabled",
            f"ActiveState={state}",
            f"SubState={sub}",
            f"Description={unit} description",
            "ActiveEnterTimestamp=Mon 2024-01-01 12:00:00 UTC",
            "Wants=rider-api.service" if unit == "rider-web-bridge.service" else "Wants=",
            "Requires=rider-broker.service" if unit == "rider-voice-web.service" else "Requires=",
        ]
    )


def test_services_graph_returns_nodes_and_edges(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    overrides = {
        "rider-voice.service": "failed",
        "rider-odometry.service": "inactive",
    }

    calls = []

    def fake_run(cmd: list[str], **_: Any):
        assert cmd[:2] == ["systemctl", "show"]
        calls.append(cmd)
        output = "\n\n".join(_fake_output(unit, overrides.get(unit, "active")) for unit in SERVICE_META)
        return SimpleNamespace(stdout=output, stderr="", returncode=0)

    monkeypatch.setattr(systemd_snapshot.subprocess, "run", fake_run)

    resp = client.get("/api/services/graph")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload is not None
    assert "nodes" in payload
    assert "edges" in payload
    nodes = payload["nodes"]
    assert len(nodes) == len(SERVICE_META)

    status_by_unit = {node["unit"]: node["status"] for node in nodes}
    assert status_by_unit["rider-voice.service"] == "failed"
    assert status_by_unit["rider-odometry.service"] == "inactive"

    edges = payload["edges"]
    assert any(
        edge["from"] == SERVICE_META["rider-web-bridge.service"]["id"]
        and edge["to"] == SERVICE_META["rider-api.service"]["id"]
        for edge in edges
    )
    assert any(
        edge["from"] == SERVICE_META["rider-voice-web.service"]["id"]
        and edge["to"] == SERVICE_META["rider-broker.service"]["id"]
        for edge in edges
    )
    assert len(calls) == 1
    assert payload["contract_version"] == 2
    assert payload["generated_at"] is not None
    assert payload["network"]["wifi"]["status"] == "connected"
