"""Producer quality fixtures only: no systemd, BUS, device or SDK calls."""

import time

import pytest
from test_task_lifecycle import World

from common.service_catalog import DEFAULT_REGISTRY, task_units


def setup(tmp_path):
    world = World()
    world.safety["owner"] = "navigation"
    manager = world.manager(tmp_path)
    # A historical/external task can still be observed, but starting this
    # implementation is unavailable. Inject recorded facts without effects.
    assert manager.set_feature("s9_navigation", True)["error"] == "navigation_traversal_unverified"
    assert world.actions == []
    manager._requested["s9_navigation"] = {}
    manager._states["s9_navigation"] = "starting"
    manager._intents["s9_navigation"] = {"generation": world.safety["generation"], "request_id": "recorded-intent"}
    world.active.update(task_units(DEFAULT_REGISTRY["s9_navigation"]))
    intent = manager._service_intents()["rider-navigator.service"]
    producer = {
        "unit": "rider-navigator.service",
        "accepted": True,
        "active": True,
        "stale": False,
        "observed_at": time.time(),
        "generation": intent["generation"],
        "request_id": intent["request_id"],
        "data_ready": True,
        "navigation_ready": True,
    }
    manager.producer_status = lambda unit: producer
    return world, manager, producer


def task(manager):
    return next(row for row in manager.describe_features() if row["name"] == "s9_navigation")


@pytest.mark.parametrize("field", ["data_ready", "navigation_ready"])
@pytest.mark.parametrize("value", [None, False, "true", 1])
def test_running_navigator_is_not_ready_without_exact_quality_flags(tmp_path, field, value):
    _, manager, producer = setup(tmp_path)
    producer[field] = value
    assert not task(manager)["ready"]
    producer.pop(field)
    assert not task(manager)["ready"]
    producer[field] = True
    assert task(manager)["ready"]


def test_matching_navigation_error_survives_stop_revocation(tmp_path):
    world, manager, producer = setup(tmp_path)
    producer.update(active=False, navigation_ready=False, data_error="navigation_traversal_unverified")
    world.safety.update(can_move=False, owner=None, generation="after-stop")
    row = task(manager)
    assert not row["ready"]
    assert row["state"] == "partial"
    assert row["error"] == row["data_error"] == "navigation_traversal_unverified"
    assert row["start_available"] is False
    assert row["planning_request_available"] is False


@pytest.mark.parametrize("change", [{"stale": True}, {"generation": "old"}, {"request_id": "other"}])
def test_unmatched_or_stale_producer_cannot_supply_current_error(tmp_path, change):
    _, manager, producer = setup(tmp_path)
    producer.update(navigation_ready=False, data_error="old-camera-failure", **change)
    row = task(manager)
    assert row["error"] == "producer_acceptance_unavailable"
    assert row["data_error"] is None
    assert not row["ready"]


def test_tracking_keeps_its_own_acceptance_contract(tmp_path):
    world = World()
    manager = world.manager(tmp_path)
    assert manager.set_feature("face_tracking", True)["ok"]
    assert next(row for row in manager.describe_features() if row["name"] == "s3_follow_me_face")["ready"]


@pytest.mark.parametrize("change", [{"data_error": "camera_failed"}, {"error": "process_failed"}, {"offline": True}])
def test_explicit_failure_denies_readiness_even_when_both_quality_flags_claim_true(tmp_path, change):
    _, manager, producer = setup(tmp_path)
    producer.update(change)
    row = task(manager)
    assert not row["ready"]
    assert row["state"] != "ready"
    if "offline" not in change:
        assert row["error"] == next(iter(change.values()))
