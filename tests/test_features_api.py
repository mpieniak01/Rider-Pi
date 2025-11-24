#!/usr/bin/env python3
from __future__ import annotations

from flask import Flask

from services.api_core import features_api


class FakeManager:
    def __init__(self) -> None:
        self.calls = []
        self.registry_dump = [
            {
                "name": "s3_follow_me_face",
                "scenario": "S3",
                "services": [],
                "active": False,
                "aliases": ["face_tracking"],
            }
        ]
        self.state_dump = {"active": ["s3_follow_me_face"], "ts": 123.0, "features": self.registry_dump}

    def set_feature(self, name: str, enabled: bool):
        if name == "unknown":
            raise ValueError("unknown feature")
        self.calls.append((name, enabled))
        return {"ok": True, "steps": [{"unit": "u", "action": "start", "ok": True}]}

    def describe_features(self):
        return self.registry_dump

    def state_snapshot(self):
        return self.state_dump


def make_app(fake_manager: FakeManager) -> Flask:
    features_api.set_feature_manager(fake_manager)
    app = Flask(__name__)
    app.add_url_rule(
        "/api/logic/feature/<name>",
        view_func=features_api.feature_handler,
        methods=["POST", "OPTIONS"],
    )
    app.add_url_rule(
        "/api/logic/features",
        view_func=features_api.feature_registry_handler,
        methods=["GET", "OPTIONS"],
    )
    app.add_url_rule(
        "/api/logic/summary",
        view_func=features_api.feature_summary_handler,
        methods=["GET", "OPTIONS"],
    )
    app.add_url_rule(
        "/api/logic/state",
        view_func=features_api.feature_state_handler,
        methods=["GET", "OPTIONS"],
    )
    return app


def test_feature_handler_ok():
    fake = FakeManager()
    app = make_app(fake)
    client = app.test_client()

    resp = client.post("/api/logic/feature/face_tracking", json={"enabled": True})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["feature"] == "face_tracking"
    assert data["enabled"] is True
    assert fake.calls == [("face_tracking", True)]


def test_feature_handler_missing_enabled():
    fake = FakeManager()
    app = make_app(fake)
    client = app.test_client()

    resp = client.post("/api/logic/feature/face_tracking", json={})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["ok"] is False
    assert data["error"] == "enabled_required"


def test_feature_handler_unknown_feature():
    fake = FakeManager()
    app = make_app(fake)
    client = app.test_client()

    resp = client.post("/api/logic/feature/unknown", json={"enabled": True})
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["ok"] is False
    assert data["error"] == "unknown_feature"


def test_feature_registry_handler_ok():
    fake = FakeManager()
    app = make_app(fake)
    client = app.test_client()

    resp = client.get("/api/logic/features")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["features"] == fake.registry_dump


def test_feature_state_handler_ok():
    fake = FakeManager()
    app = make_app(fake)
    client = app.test_client()

    resp = client.get("/api/logic/state")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["state"] == fake.state_dump


def test_feature_summary_handler_ok():
    fake = FakeManager()
    app = make_app(fake)
    client = app.test_client()

    resp = client.get("/api/logic/summary")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    summary = data["summary"]
    assert summary["counts"]["total"] == 1
    assert summary["features"][0]["name"] == "s3_follow_me_face"
