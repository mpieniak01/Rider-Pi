"""Main/watchdog lifecycle races with real classes and memory-only authority."""

import json
import threading

import pytest
from test_journey_runner import runner
from test_navigation_runner import isolated as isolated


def launch(name, callback, errors):
    def capture():
        try:
            callback()
        except Exception as exc:
            errors.append((name, type(exc).__name__, str(exc)))

    thread = threading.Thread(name=name, target=capture, daemon=True)
    thread.start()
    return thread


def test_main_and_watchdog_retire_journey_once_without_closing_warm_producer(isolated, monkeypatch):
    instance, safety = runner(isolated)
    old_lease = instance.lease
    entered, resume, watchdog_done = threading.Event(), threading.Event(), threading.Event()
    errors = []
    original_end = old_lease.journey.end

    def paused_end(reason):
        original_end(reason)
        if threading.current_thread().name == "navigation-main":
            entered.set()
            assert resume.wait(2)

    monkeypatch.setattr(old_lease.journey, "end", paused_end)
    safety.update(state="DISARMED", can_move=False, owner=None, generation="after-stop")
    safety["journey"].update(active=False, reason="operator_stop")
    main = launch("navigation-main", instance._authority, errors)
    assert entered.wait(1)

    def watchdog_sync():
        instance._authority()
        watchdog_done.set()

    watch = launch("navigation-watchdog", watchdog_sync, errors)
    raced = watchdog_done.wait(0.1)
    resume.set()
    main.join(2)
    watch.join(2)
    assert not main.is_alive() and not watch.is_alive()
    assert errors == []
    assert not raced
    assert not instance.closed.is_set()
    assert instance.policy["mode"] == "observe"
    assert instance.lease.journey is None
    assert instance.operator_lifecycle.last_journey["id"] == "mission"
    assert old_lease.journey.active is False
    assert instance.generation == "after-stop"


def test_status_waits_for_complete_lease_generation_transition(isolated, monkeypatch, tmp_path):
    instance, safety = runner(isolated)
    lifecycle = instance.operator_lifecycle
    entered, resume, status_done = threading.Event(), threading.Event(), threading.Event()
    errors = []
    original_reset = lifecycle._reset_lease

    def paused_reset(authority, *, authorized):
        original_reset(authority, authorized=authorized)
        entered.set()
        assert resume.wait(2)

    monkeypatch.setattr(lifecycle, "_reset_lease", paused_reset)
    safety.update(state="DISARMED", can_move=False, owner=None, generation="after-stop")
    safety["journey"].update(active=False, reason="operator_stop")
    main = launch("navigation-main", instance._authority, errors)
    assert entered.wait(1)

    def publish():
        instance._status(None)
        status_done.set()

    observer = launch("navigation-status", publish, errors)
    raced = status_done.wait(0.1)
    resume.set()
    main.join(2)
    observer.join(2)
    assert not main.is_alive() and not observer.is_alive()
    assert errors == []
    assert not raced
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["generation"] == instance.generation == "after-stop"
    assert status["run_id"] == instance.run_id
    assert status["operator_request_id"] is None
    assert status["mode"] == "observe"
    assert status["journey"]["active"] is False


def test_identity_failure_halts_lease_outside_lifecycle_mutex(isolated, monkeypatch):
    from apps.compute.client import ComputeError

    instance, _ = runner(isolated)
    lease = instance.lease
    lease_owned, validating, callback_entered = threading.Event(), threading.Event(), threading.Event()
    errors, rejected = [], []

    def invalid_reply(_decision):
        validating.set()
        assert callback_entered.wait(2)
        return False

    monkeypatch.setattr(lease.journey, "validate_reply", invalid_reply)

    def lease_callback():
        # DecisionLease.accept/tick can call authority while holding this lock.
        with lease.lock:
            lease_owned.set()
            assert validating.wait(2)
            callback_entered.set()
            instance._authority()

    def failed_evidence():
        assert lease_owned.wait(2)
        try:
            instance.operator_lifecycle.evidence({}, "frame", 1, instance.clock())
        except ComputeError as exc:
            rejected.append(exc.code)

    actuator = launch("navigation-lease-callback", lease_callback, errors)
    evidence = launch("navigation-evidence", failed_evidence, errors)
    actuator.join(2)
    evidence.join(2)
    assert not actuator.is_alive() and not evidence.is_alive()
    assert errors == []
    assert rejected == ["navigation_journey_identity_mismatch"]
    assert lease.latched
    assert instance._authority() is False
    assert instance.policy["mode"] == "observe"
    assert all(row["expected_generation"] == "gen" for row in isolated[-1])


def test_old_reply_cannot_label_new_epoch_status(isolated, tmp_path):
    instance, safety = runner(isolated)
    old_run = instance.run_id
    safety.update(state="DISARMED", can_move=False, owner=None, generation="after-stop")
    safety["journey"].update(active=False, reason="operator_stop")
    assert instance._authority() is False
    instance._status({"run_id": old_run, "action": "go", "state": "clear"})
    row = json.loads((tmp_path / "status.json").read_text())
    assert row["run_id"] == instance.run_id != old_run
    assert row["generation"] == "after-stop"
    assert row["decision"] is None
    assert row["mode"] == "observe"


@pytest.mark.parametrize("field", ["deadline", "feedback_deadline"])
def test_status_samples_expiring_deadline_once_without_none_arithmetic(isolated, monkeypatch, tmp_path, field):
    instance, _ = runner(isolated)
    lease = instance.lease
    expires, reads = instance.clock() + 0.1, []

    def disappearing(_self):
        reads.append(field)
        return expires if len(reads) <= 2 else None

    monkeypatch.setattr(type(lease), field, property(disappearing), raising=False)
    instance._status(None)
    row = json.loads((tmp_path / "status.json").read_text())
    key = "permit_remaining_ms" if field == "deadline" else "feedback_remaining_ms"
    assert 0 < row[key] <= 100
    assert reads == [field]
