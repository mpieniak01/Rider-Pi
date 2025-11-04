from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from flask import Flask

from services.api_core import services_dashboard_api
from services.api_core.service_meta import SERVICE_META


@pytest.fixture()
def client() -> Iterator[Any]:
    app = Flask(__name__)
    app.register_blueprint(services_dashboard_api.bp)
    with app.test_client() as test_client:
        yield test_client


def _fake_output(unit: str, state: str) -> str:
    sub = "running" if state == "active" else ("failed" if state == "failed" else "dead")
    return "\n".join(
        [
            f"Id={unit}",
            f"ActiveState={state}",
            f"SubState={sub}",
            f"Description={unit} description",
            "ActiveEnterTimestamp=Mon 2024-01-01 12:00:00 UTC",
        ]
    )


def test_services_graph_returns_nodes_and_edges(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    overrides = {
        "rider-voice.service": "failed",
        "rider-odometry.service": "inactive",
    }

    def fake_check_output(cmd: list[str], **_: Any) -> str:
        assert cmd[:2] == ["systemctl", "show"]
        unit = cmd[2]
        state = overrides.get(unit, "active")
        return _fake_output(unit, state)

    monkeypatch.setattr(services_dashboard_api.subprocess, "check_output", fake_check_output)

    resp = client.get("/api/services/graph")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload is not None
    assert "nodes" in payload and "edges" in payload
    nodes = payload["nodes"]
    assert len(nodes) == len(SERVICE_META)

    status_by_unit = {node["unit"]: node["status"] for node in nodes}
    assert status_by_unit["rider-voice.service"] == "failed"
    assert status_by_unit["rider-odometry.service"] == "inactive"

    edges = payload["edges"]
    assert any(edge["from"] == "web-bridge" and edge["to"] == "api" for edge in edges)
    assert any(edge["from"] == "voice-web" and edge["to"] == "voice" for edge in edges)
    assert payload["generated_at"] is not None
