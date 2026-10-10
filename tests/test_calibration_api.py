"""Flask/fake runtime tests only. Publishers are always replaced before requests."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from apps.motion import calibration_profiles as store
from services import calibration_api as api


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("RIDER_CALIBRATION_DIR", str(tmp_path / "profiles"))
    clock = SimpleNamespace(now=1000.0)
    record = json.loads((Path(__file__).parents[1] / "config/odometry-calibration.example.json").read_text())
    profile = {
        "schema_version": 1,
        "name": "Fake configuration",
        "provenance": {"kind": "draft", "notes": ""},
        "motion": {"speed_limit": 0.4, "linear_rate": 0.8, "turn_rate": 1.2},
        "odometry": record,
        "measurements": [],
    }
    motion = {
        "contract_version": 1,
        "state": "DISARMED",
        "generation": "fake-generation",
        "last_seq": -1,
        "observed_at": clock.now,
        "instance_id": "fake-executor",
        "ready": False,
        "moving": False,
        "target": {"lx": 0, "az": 0},
        "output": {"lx": 0, "az": 0},
    }
    odometry = {"contract_version": 1, "observed_at": clock.now, "instance_id": "fake-odometry", "started_at": 900}
    sent = []
    monkeypatch.setattr(api, "wall_clock", lambda: clock.now)
    monkeypatch.setattr(api, "read_status", lambda: copy.deepcopy(motion))
    monkeypatch.setattr(api, "odometry_snapshot", lambda: copy.deepcopy(odometry))
    monkeypatch.setattr(api, "_publish", lambda row: sent.append(copy.deepcopy(row)))
    monkeypatch.setattr(api, "_pending", None)
    app = Flask(__name__)
    app.add_url_rule("/api/calibration/state", view_func=api.state)
    app.add_url_rule("/api/calibration/profiles", view_func=api.catalog, methods=["GET", "POST"])
    app.add_url_rule("/api/calibration/profiles/<digest>", view_func=api.profile)
    app.add_url_rule("/api/calibration/activate", view_func=api.activate, methods=["POST"])
    return SimpleNamespace(
        clock=clock,
        profile=profile,
        motion=motion,
        odometry=odometry,
        sent=sent,
        client=app.test_client(),
        monkeypatch=monkeypatch,
    )


def command(world, digest, **changes):
    return {
        "profile_digest": digest,
        "request_id": "fake-apply",
        "generation": "fake-generation",
        "source": "manual",
        "seq": 1,
        "ts": world.clock.now,
        "ttl_ms": 500,
        "operator_consent": True,
        "operator_plan": "Fake DISARMED configuration only",
        **changes,
    }


def applied(world):
    digest = store.save_profile(world.profile)["digest"]
    pointer = store.write_active(digest, request_id="fake-apply", command_generation="fake-generation", seq=1, now=1000)
    ack = {
        "action": "activate_calibration",
        "status": "executed",
        "accepted": True,
        "request_id": "fake-apply",
        "source": "manual",
        "seq": 1,
        "command_generation": "fake-generation",
        "generation": "after-config",
        "profile_digest": digest,
        "observed_at": 1000,
        "instance_id": "fake-executor",
        "actuation": False,
        "physical_completion": "unverified",
    }
    world.motion["calibration"] = {
        "profile_digest": digest,
        "source": "profile",
        "observed_at": 1000,
        "instance_id": "fake-executor",
        "activation_request_id": "fake-apply",
        "command_generation": "fake-generation",
        "applied_generation": "after-config",
        "applied_ack": ack,
        "last_ack": ack,
    }
    world.odometry["calibration"] = {
        "profile_digest": digest,
        "source": "profile",
        "observed_at": 1000,
        "motion_instance_id": "fake-executor",
        "activation_request_id": "fake-apply",
        "command_generation": "fake-generation",
        "applied_generation": "after-config",
        "seq": 1,
        "model_ready": False,
        "odometry_error": "manual_calibration_required",
    }
    return pointer


def test_get_save_and_import_never_publish_or_activate(world):
    assert world.client.get("/api/calibration/state").json["status"] == "unconfigured"
    assert world.client.get("/api/calibration/profiles").json["profiles"] == []
    response = world.client.post("/api/calibration/profiles", json={"profile": world.profile})
    assert response.status_code == 201 and response.json["created"]
    digest = response.json["digest"]
    assert world.client.get("/api/calibration/profiles/" + digest).json["profile"] == response.json["profile"]
    assert world.client.post("/api/calibration/profiles", json={"profile": world.profile}).status_code == 200
    imported = copy.deepcopy(world.profile)
    imported["odometry"]["manual_verified"] = True
    imported["provenance"]["kind"] = "manual"
    response = world.client.post("/api/calibration/profiles", json={"profile": imported, "imported": True})
    assert response.json["profile"]["provenance"]["kind"] == "historical"
    assert response.json["profile"]["odometry"]["manual_verified"] is False
    assert store.read_active() is None and not world.sent


def test_activate_preserves_caller_envelope_and_202_is_not_confirmation(world):
    digest = store.save_profile(world.profile)["digest"]
    row = command(world, digest)
    response = world.client.post("/api/calibration/activate", json=row)
    assert response.status_code == 202 and response.json["pending"] and response.json["accepted"] is False
    assert world.sent == [dict(row, action="activate_calibration")]
    assert store.read_active() is None
    snapshot = world.client.get("/api/calibration/state").json
    assert snapshot["status"] == "pending" and snapshot["confirmation"] == "unconfirmed"
    assert snapshot["model_ready"] is False and snapshot["actuation"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"operator_consent": False},
        {"operator_plan": ""},
        {"generation": "old"},
        {"source": "navigation"},
        {"seq": True},
        {"seq": -1},
        {"seq": 2**63},
        {"ts": 999},
        {"ts": 1001},
        {"ttl_ms": 501},
        {"request_id": ""},
        {"action": "move"},
    ],
)
def test_invalid_activation_never_publishes(world, changes):
    digest = store.save_profile(world.profile)["digest"]
    response = world.client.post("/api/calibration/activate", json=command(world, digest, **changes))
    assert response.status_code == 409 and response.json["accepted"] is False and not world.sent


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "ARMED"},
        {"state": "ESTOP"},
        {"state": "UNKNOWN"},
        {"moving": True},
        {"observed_at": 995},
        {"target": {"lx": 0.1, "az": 0}},
        {"output": {"lx": 0, "az": -0.1}},
        {"last_seq": 1},
    ],
)
def test_nonidle_or_stale_or_replayed_runtime_blocks_configuration(world, changes):
    digest = store.save_profile(world.profile)["digest"]
    world.motion.update(changes)
    assert world.client.post("/api/calibration/activate", json=command(world, digest)).status_code == 409
    assert not world.sent and store.read_active() is None


def test_unavailable_odometry_and_transport_are_explicit_no_service_start(world):
    digest = store.save_profile(world.profile)["digest"]
    world.odometry["observed_at"] = 900
    assert world.client.post("/api/calibration/activate", json=command(world, digest)).status_code == 503
    assert not world.sent
    world.odometry["observed_at"] = 1000

    def failed(row):
        raise RuntimeError("Fake unavailable transport")

    world.monkeypatch.setattr(api, "_publish", failed)
    assert world.client.post("/api/calibration/activate", json=command(world, digest)).status_code == 503
    assert store.read_active() is None


def test_applied_configuration_does_not_claim_calibrated_physics(world):
    pointer = applied(world)
    state = world.client.get("/api/calibration/state").json
    assert state["active"] == pointer and state["status"] == "applied" and state["confirmation"] == "executed"
    assert state["model_ready"] is False and state["calibration_error"] == "manual_calibration_required"
    assert state["motion"]["ready"] is False and state["physical_completion"] == "unverified"


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile_digest", "0" * 64),
        ("applied_generation", "wrong-accepted-generation"),
        ("activation_request_id", "previous"),
        ("command_generation", "previous"),
        ("motion_instance_id", "previous-process"),
        ("seq", 9),
        ("observed_at", 900),
        ("error", "load_failed"),
    ],
)
def test_current_hash_is_insufficient_without_matching_odometry_process(world, field, value):
    applied(world)
    world.odometry["calibration"][field] = value
    assert world.client.get("/api/calibration/state").json["status"] == "partial"


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", "old"),
        ("command_generation", "old"),
        ("instance_id", "old"),
        ("observed_at", 999),
        ("accepted", False),
        ("seq", 10),
        ("actuation", True),
    ],
)
def test_generic_or_old_or_wrong_ack_is_not_applied(world, field, value):
    applied(world)
    world.motion["calibration"]["applied_ack"][field] = value
    assert world.client.get("/api/calibration/state").json["confirmation"] == "unconfirmed"


def test_retained_success_ack_is_not_replaced_by_later_rejection(world):
    applied(world)
    world.motion["calibration"]["last_ack"] = {"accepted": False, "request_id": "another-rejected-attempt"}
    assert world.client.get("/api/calibration/state").json["status"] == "applied"
    world.clock.now = 2000
    for value in (world.motion, world.odometry, world.motion["calibration"], world.odometry["calibration"]):
        value["observed_at"] = 2000
    assert world.client.get("/api/calibration/state").json["status"] == "applied"  # fresh loaded state, old ACK


def test_saved_configuration_recovery_is_not_a_new_execution(world):
    applied(world)
    for value in (world.motion["calibration"], world.odometry["calibration"]):
        value.update(source="saved_profile", activation_request_id=None, applied_generation=None)
    world.motion["calibration"].update(applied_ack=None, last_ack=None)
    state = world.client.get("/api/calibration/state").json
    assert state["status"] == "applied" and state["confirmation"] == "loaded_from_saved"
    world.odometry["calibration"]["motion_instance_id"] = "old-process"
    assert world.client.get("/api/calibration/state").json["status"] == "partial"


def test_pending_timeout_and_rejected_attempt_are_partial(world):
    digest = store.save_profile(world.profile)["digest"]
    row = command(world, digest)
    world.client.post("/api/calibration/activate", json=row)
    world.clock.now += 6
    assert world.client.get("/api/calibration/state").json["error"] == "activation_confirmation_timeout"
    world.motion["observed_at"] = world.clock.now
    world.motion["calibration"] = {
        "last_ack": dict(
            row, accepted=False, command_generation=row["generation"], error="environment_ceiling_exceeded"
        )
    }
    assert world.client.get("/api/calibration/state").json["error"] == "environment_ceiling_exceeded"


@pytest.mark.parametrize("raw", ['{"profile":{},"profile":{}}', '{"profile":{"number":NaN}}', '[]'])
def test_malformed_or_duplicate_or_nonfinite_request_is_rejected(world, raw):
    response = world.client.post("/api/calibration/profiles", data=raw, content_type="application/json")
    assert response.status_code == 400 and not world.sent and store.read_active() is None


def test_busy_store_and_route_registration(world):
    def busy(*args):
        raise BlockingIOError("Fake contention")

    world.monkeypatch.setattr(store.fcntl, "flock", busy)
    response = world.client.post("/api/calibration/profiles", json={"profile": world.profile})
    assert response.status_code == 409 and response.json["error"] == "calibration_busy"
    from services.api_server import app

    expected = {
        "/calibration",
        "/api/calibration/state",
        "/api/calibration/profiles",
        "/api/calibration/profiles/<digest>",
        "/api/calibration/activate",
    }
    assert expected <= {str(rule) for rule in app.url_map.iter_rules()}


def reference_http(world):
    from services import odometry_api

    world.motion["ready"] = True
    world.monkeypatch.setattr(odometry_api, "read_status", lambda: copy.deepcopy(world.motion))
    world.monkeypatch.setattr(odometry_api, "snapshot", lambda: copy.deepcopy(world.odometry))
    world.monkeypatch.setattr(odometry_api, "wall_clock", lambda: world.clock.now)
    publisher = SimpleNamespace(publish=lambda topic, row, **kwargs: world.sent.append((topic, row, kwargs)))
    world.monkeypatch.setattr(odometry_api, "_publisher", publisher)
    world.client.application.add_url_rule(
        "/api/odometry/reference", view_func=odometry_api.operator_reference, methods=["POST"]
    )
    row = command(world, world.motion.get("calibration", {}).get("profile_digest"))
    return dict(row, x=1.0, y=2.0, theta=0.0, request_id="fake-reference")


def test_reference_http_carries_expected_profile_without_mutation(world):
    pointer = applied(world)
    row = reference_http(world)
    response = world.client.post("/api/odometry/reference", json=row)
    assert response.status_code == 202 and response.json["profile_digest"] == pointer["profile_digest"]
    assert world.sent == [("odometry.reference", row, {"add_ts": False})]
    assert store.read_active() == pointer


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile_digest", "0" * 64),
        ("motion_instance_id", "old-executor"),
        ("activation_request_id", "old-activation"),
        ("applied_generation", "old-accepted-generation"),
        ("seq", 9),
        ("observed_at", 900),
        ("error", "model_not_loaded"),
    ],
)
def test_reference_http_denies_old_or_unconfirmed_odometry_before_bus(world, field, value):
    applied(world)
    row = reference_http(world)
    world.odometry["calibration"][field] = value
    response = world.client.post("/api/odometry/reference", json=row)
    assert response.status_code == 409 and response.json["error"] == "reference_profile_unconfirmed"
    assert not world.sent


def test_reference_http_requires_active_digest_and_rechecks_generation(world):
    applied(world)
    row = reference_http(world)
    assert world.client.post("/api/odometry/reference", json=dict(row, profile_digest=None)).status_code == 409
    from services import odometry_api

    calls = []

    def changed_state():
        calls.append(True)
        return dict(world.motion, generation="later-generation") if len(calls) > 1 else copy.deepcopy(world.motion)

    world.monkeypatch.setattr(odometry_api, "read_status", changed_state)
    response = world.client.post("/api/odometry/reference", json=row)
    assert response.status_code == 409 and response.json["error"] == "stale_generation" and not world.sent


def test_reference_http_preserves_explicit_legacy_file_contract(world):
    row = reference_http(world)
    row.pop("profile_digest")
    assert world.client.post("/api/odometry/reference", json=row).status_code == 202
    assert world.sent[0][1] == row
