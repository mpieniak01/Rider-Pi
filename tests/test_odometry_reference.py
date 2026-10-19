"""Reference API/BUS tests with fake publishers, files in tmp_path, no robot."""

import json
from types import SimpleNamespace

import pytest
from flask import Flask

from apps.odometry.main import OdometryEstimator
from apps.odometry.reference import ReferenceControl, reference_paths
from services import odometry_api


@pytest.fixture
def world(monkeypatch, tmp_path):
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setenv("ODOMETRY_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(odometry_api, "wall_clock", lambda: clock.now)
    state = {
        "contract_version": 1,
        "state": "DISARMED",
        "ready": True,
        "hardware_ready": True,
        "moving": False,
        "generation": "fake-generation",
        "observed_at": clock.now,
    }
    estimator = OdometryEstimator(calibration={}, clock=lambda: clock.now, wall_clock=lambda: clock.now)
    sent = []
    publisher = SimpleNamespace(publish=lambda *args, **kw: sent.append(args))
    control = ReferenceControl(estimator, publisher, safety_reader=lambda: dict(state), clock=lambda: clock.now)
    control.publish_status(force=True)
    monkeypatch.setattr(odometry_api, "read_status", lambda: dict(state))
    monkeypatch.setattr(odometry_api, "_publisher", publisher)
    app = Flask(__name__)
    app.add_url_rule("/state", view_func=odometry_api.reference_state)
    app.add_url_rule("/reference", view_func=odometry_api.operator_reference, methods=["POST"])
    return SimpleNamespace(
        clock=clock,
        state=state,
        estimator=estimator,
        control=control,
        sent=sent,
        client=app.test_client(),
        publisher=publisher,
    )


def request_row(world, **fields):
    return {
        "generation": world.state["generation"],
        "source": "manual",
        "seq": 1,
        "request_id": "operator-origin",
        "ts": world.clock.now,
        "ttl_ms": 500,
        "operator_consent": True,
        "operator_plan": "Verify fictional origin in mock fixture",
        "x": 1.0,
        "y": 2.0,
        "theta": 0.5,
        **fields,
    }


def test_get_never_publishes_and_post_is_pending_until_domain_ack(world):
    assert world.client.get("/state").status_code == 200
    assert not world.sent
    row = request_row(world)
    response = world.client.post("/reference", json=row)
    assert response.status_code == 202
    assert response.json["status"] == "pending"
    assert "accepted" not in response.json
    assert not world.estimator.reference_verified
    assert world.sent == [("odometry.reference", row)]
    ack = world.control.apply(row)
    assert ack["status"] == "executed"
    assert ack["actuation"] is False
    assert ack["physical_completion"] == "unverified"
    assert world.client.get("/state").json["reference_id"] == "operator-origin"


@pytest.mark.parametrize(
    "fields",
    [
        {"operator_consent": False},
        {"operator_plan": ""},
        {"source": "navigation"},
        {"generation": "previous"},
        {"ts": 999},
        {"ttl_ms": 501},
        {"seq": True},
        {"x": True},
        {"x": float("nan")},
        {"request_id": ""},
        {"home_operator_confirmed": True},
        {"home_operator_confirmed": True, "home_x": 0, "home_y": float("nan")},
        {"home_operator_confirmed": False, "home_x": 0, "home_y": 0},
        {"home_operator_confirmed": "true", "home_x": 0, "home_y": 0},
    ],
)
def test_invalid_reference_rejected_by_process(world, fields):
    assert world.control.apply(request_row(world, **fields))["status"] == "rejected"
    assert not world.estimator.reference_verified


@pytest.mark.parametrize(
    "fields", [{"state": "ARMED"}, {"state": "UNKNOWN"}, {"ready": False}, {"moving": True}, {"observed_at": 996}]
)
def test_reference_requires_confirmed_fresh_stationary_disarmed(world, fields):
    world.state.update(fields)
    assert world.client.post("/reference", json=request_row(world)).status_code == 409
    assert world.control.apply(request_row(world))["status"] == "rejected"
    assert not world.estimator.reference_verified


def test_restart_never_restores_reference_and_persistent_replay_is_denied(world):
    row = request_row(world)
    assert world.control.apply(row)["status"] == "executed"
    replacement = OdometryEstimator(calibration={})
    process = ReferenceControl(
        replacement, world.publisher, safety_reader=lambda: world.state, clock=lambda: world.clock.now
    )
    assert not replacement.reference_verified
    assert process.apply(row)["error"] == "reference_replayed"
    world.clock.now += 0.1
    process = ReferenceControl(
        replacement, world.publisher, safety_reader=lambda: world.state, clock=lambda: world.clock.now
    )
    assert process.apply(request_row(world, seq=2, ts=1000))["error"] == "reference_before_process_start"


def test_corrupt_consumption_journal_denies_reference(world):
    _, path = reference_paths()
    path.write_text("not JSON")
    assert world.control.apply(request_row(world))["error"] == "reference_journal_unavailable"
    assert not world.estimator.reference_verified


def test_safety_becoming_not_ready_during_reference_invalidates_it(world):
    original = world.estimator.set_reference

    def change(**kw):
        result = original(**kw)
        world.state["ready"] = False
        return result

    world.estimator.set_reference = change
    assert world.control.apply(request_row(world))["error"] == "safety_changed_during_reference"
    assert not world.estimator.reference_verified


@pytest.mark.parametrize(
    "fields",
    [
        {"contract_version": 0},
        {"instance_id": ""},
        {"started_at": None},
        {"started_at": 1001},
        {"pose": {}},
        {"reference_verified": None},
        {"reference_id": "false-reference"},
        {"last_ack": []},
        {"contract_version": True},
        {"home": {"x": 0, "y": 0}},
    ],
)
def test_corrupt_process_snapshot_cannot_publish_reference(world, fields):
    path, _ = reference_paths()
    value = json.loads(path.read_text())
    value.update(fields)
    path.write_text(json.dumps(value))
    assert world.client.get("/state").json["error"] == "odometry_unavailable"
    assert world.client.post("/reference", json=request_row(world)).status_code == 503
    assert not world.sent


def test_publisher_constructor_failure_returns_explicit_unavailable(world, monkeypatch):
    monkeypatch.setattr(odometry_api, "_publisher", None)

    def unavailable():
        raise RuntimeError("fake BUS unavailable")

    monkeypatch.setattr(odometry_api, "BusPub", unavailable)
    response = world.client.post("/reference", json=request_row(world))
    assert response.status_code == 503
    assert response.json["error"] == "reference_transport_failed"


def test_reference_without_home_cannot_restore_previous_home(world):
    with_home = request_row(world, home_operator_confirmed=True, home_x=4, home_y=5)
    assert world.control.apply(with_home)["status"] == "executed"
    projected = world.client.get("/state").json
    assert projected["home"]["x"] == 4
    assert projected["home"]["reference_id"] == "operator-origin"
    assert not projected["pose"]["navigation_ready"]
    assert world.control.apply(request_row(world, seq=2, request_id="current-point-only"))["status"] == "executed"
    assert world.estimator.home is None
    assert world.client.get("/state").json["home"] is None
