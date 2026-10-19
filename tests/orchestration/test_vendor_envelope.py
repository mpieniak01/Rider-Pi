"""Synthetic HTTP-only contract tests; all effectful interfaces are denied by fixtures."""

from __future__ import annotations

import math

import pytest
from flask import Flask, Response, jsonify, request

from services.api_core import http_contract
from services.api_core.contract_registry import projection, service_row

VENDOR = {"Accept": "application/vnd.rider.api+json;version=1"}


@pytest.fixture
def world():
    app = Flask(__name__)
    http_contract.install(app, after_request=True)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    payload = {
        "ok": True,
        "observed_at": None,
        "ts": 1000,
        "battery": 0,
        "enabled": False,
        "extra": {"extension": "retained"},
    }
    effects = []

    @app.route("/state", methods=["GET", "POST"])
    def state():
        if request.method == "POST":
            effects.append(request.get_json())
        return jsonify(payload)

    @app.route("/api/logic/feature/<name>", methods=["POST"])
    def feature(name):
        return jsonify(payload)

    @app.route("/api/safety", methods=["POST"])
    def safety():
        return jsonify(payload), 202 if payload.get("pending") else 200

    @app.route("/camera/raw")
    def raw():
        return Response(b"JPEG fixture", mimetype="image/jpeg")

    @app.route("/events")
    def events():
        return Response("data: {}\n\n", mimetype="text/event-stream")

    @app.route("/explode")
    def explode():
        raise RuntimeError("synthetic")

    return app.test_client(), payload, effects


def test_legacy_and_negotiated_projection(world):
    client, _, _ = world
    legacy = client.get("/state").get_json()
    response = client.get("/state", headers=VENDOR)
    row = response.get_json()
    assert response.content_type == "application/vnd.rider.api+json;version=1"
    assert "Accept" in response.vary
    assert row["meta"]["contract_id"] == "rider.telemetry"
    assert row["meta"]["observed_at"] is None
    assert row["meta"]["generated_at"] > 0
    assert row["data"] == {key: value for key, value in legacy.items() if key != "ok"}
    assert row["data"]["battery"] == 0
    assert row["data"]["enabled"] is False
    assert "battery" not in row
    assert row["operation"] is None


@pytest.mark.parametrize("version", ["2", "99", "missing"])
def test_unknown_version_is_denied_before_effect(world, version):
    client, _, effects = world
    suffix = "" if version == "missing" else ";version=" + version
    response = client.post("/state", json={}, headers={"Accept": "application/vnd.rider.api+json" + suffix})
    assert response.status_code == 406
    assert response.get_json()["error"]["code"] == "unsupported_envelope_version"
    assert effects == []


@pytest.mark.parametrize("accept", ["application/json", "application/vnd.rider.api+json;version=9;q=0"])
def test_legacy_and_zero_quality(world, accept):
    client, _, _ = world
    assert "meta" not in client.get("/state", headers={"Accept": accept}).get_json()


def test_supported_choice_cors_options_and_head(world):
    client, _, effects = world
    headers = {"Accept": "application/vnd.rider.api+json;version=2,application/vnd.rider.api+json;version=1;q=.5"}
    assert client.get("/state", headers=headers).get_json()["meta"]["envelope_version"] == 1
    response = client.options("/state", headers={**VENDOR, "Origin": "http://localhost"})
    assert response.status_code == 204
    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]
    assert "Accept" in response.headers["Access-Control-Allow-Headers"]
    assert client.head("/state", headers=VENDOR).data == b""
    assert effects == []


@pytest.mark.parametrize(
    "path,method,code", [("/unknown", "get", 404), ("/camera/raw", "post", 405), ("/explode", "get", 500)]
)
def test_error_handlers_keep_envelope(world, path, method, code):
    client, _, _ = world
    response = getattr(client, method)(path, headers=VENDOR)
    assert response.status_code == code
    assert response.get_json()["ok"] is False
    assert response.get_json()["error"]["code"]


@pytest.mark.parametrize("path,mime", [("/camera/raw", "image/jpeg"), ("/events", "text/event-stream")])
def test_binary_and_stream_mime_unchanged(world, path, mime):
    client, _, _ = world
    assert client.get(path, headers=VENDOR).mimetype == mime


def test_pending_and_unproven_success_are_not_confirmed(world):
    client, payload, _ = world
    payload.update(ok=True, request_id="fixture", pending=True)
    response = client.post("/api/safety", json={"action": "stop"}, headers=VENDOR)
    assert response.status_code == 202
    assert response.get_json()["operation"]["confirmed"] is False
    assert response.get_json()["operation"]["target"] == "motion-executor"
    payload.pop("pending")
    response = client.post("/state", json={}, headers=VENDOR)
    assert response.status_code == 502
    assert response.get_json()["operation"]["status"] == "unknown"


def test_starting_task_is_accepted_pending_and_error_retained(world):
    client, payload, _ = world
    payload.clear()
    payload.update(ok=True, result={"ok": True, "task": {"state": "starting", "ready": False}})
    row = client.post("/api/logic/feature/task", json={"enabled": True}, headers=VENDOR)
    assert row.status_code == 202
    assert row.get_json()["operation"]["ack_kind"] == "task_accepted"
    payload.update(ok=False, result={"ok": False, "error": "producer_failed"})
    assert (
        client.post("/api/logic/feature/task", json={}, headers=VENDOR).get_json()["error"]["code"] == "producer_failed"
    )


def test_sensor_partial_is_a_valid_get_with_domain_error(world):
    client, payload, _ = world
    payload["error"] = "sensor_quality:yaw_unavailable"
    row = client.get("/state", headers=VENDOR).get_json()
    assert row["ok"]
    assert row["meta"]["partial"]
    assert row["data"]["battery"] == 0
    assert row["data"]["error"] == payload["error"]


@pytest.mark.parametrize("value", [math.inf, math.nan])
def test_nonfinite_source_is_explicit_protocol_failure(world, value):
    client, payload, _ = world
    payload["battery"] = value
    row = client.get("/state", headers=VENDOR)
    assert row.status_code == 502
    assert row.get_json()["error"]["code"] == "invalid_domain_payload"


def test_process_running_does_not_mean_active_target_and_identity_is_consistent():
    target = service_row({"unit": "rider-tracker.target", "active": "active", "sub": "exited", "pid": 0})
    assert target["active_state"] == "active"
    assert target["process_running"] is False
    assert service_row({"unit": "rider-api.service", "active": "active"})["process_running"] is None
    row = service_row({"unit": "rider-api.service", "active": "active", "pid": 10, "edges_out": ["broker"]})
    assert row["process_running"] is True
    assert row["edges_out"] == ["pi:rider-broker.service"]


def test_nested_task_state_uses_same_observed_service_shape():
    data = projection(
        "/api/logic/state",
        {
            "state": {
                "features": [
                    {
                        "name": "s6_tracker_module",
                        "services": [
                            {"unit": "rider-tracker.target", "active": True, "active_state": "active", "pid": 0}
                        ],
                    }
                ]
            }
        },
    )
    task = data["state"]["features"][0]
    assert task["identity"] == "pi:s6_tracker_module"
    assert task["services"][0]["active_state"] == "active"
    assert task["services"][0]["process_running"] is False


@pytest.mark.parametrize(
    "status,confirmed,domain_code,expected_code",
    [
        ("executed", True, 201, 201),
        ("pending", False, 200, 202),
        ("unknown", False, 200, 502),
        ("partial", False, 200, 409),
        ("executed", True, 422, 422),
        ("partial", False, 503, 503),
    ],
)
def test_explicit_operation_evidence_maps_success_and_preserves_domain_errors(
    status, confirmed, domain_code, expected_code
):
    app = Flask(__name__)
    http_contract.install(app, after_request=True)
    evidence = {"status": status, "confirmed": confirmed, "request_id": "domain-fixture"}

    @app.route("/fixture")
    def domain():
        http_contract.operation(evidence)
        return jsonify({"ok": True, "value": 0}), domain_code

    response = app.test_client().get("/fixture", headers=VENDOR)
    row = response.get_json()
    assert response.status_code == expected_code
    assert row["operation"] == evidence
    assert row["ok"] is (confirmed and expected_code < 400)
    assert row["meta"]["partial"] is (status == "partial")
    if expected_code < 400:
        assert row["error"] is None
    else:
        assert row["error"]["code"] == f"http_{expected_code}"


@pytest.mark.parametrize("source", [None, [], {"value": 0}])
def test_explicit_canonical_data_preserves_empty_sources(source):
    app = Flask(__name__)
    http_contract.install(app, after_request=True)

    @app.route("/fixture")
    def domain():
        http_contract.canonical_data(source)
        return jsonify({"ok": True, "legacy": "must not replace canonical data"})

    response = app.test_client().get("/fixture", headers=VENDOR)
    assert response.status_code == 200
    assert response.get_json()["data"] == source


def test_unserializable_canonical_source_is_a_protocol_failure():
    app = Flask(__name__)
    http_contract.install(app, after_request=True)

    @app.route("/fixture")
    def domain():
        http_contract.canonical_data({"unsupported": {1, 2}})
        return jsonify({"ok": True})

    response = app.test_client().get("/fixture", headers=VENDOR)
    row = response.get_json()
    assert response.status_code == 502
    assert row["ok"] is False
    assert row["meta"]["partial"] is True
    assert row["data"] is None
    assert row["operation"] is None
    assert row["error"]["code"] == "invalid_domain_payload"
    assert response.content_type == "application/vnd.rider.api+json;version=1"
    assert response.headers["Cache-Control"] == "no-store"
