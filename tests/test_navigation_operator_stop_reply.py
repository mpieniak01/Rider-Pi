"""An accepted operator STOP precedes its cancelled reference reply, never GO."""

import io
import json
import time
import urllib.error

import pytest
from navigation_runner_fixtures import isolated as isolated
from test_journey_runner import runner

from apps.compute import navigation


def stopped_snapshot(safety, *, ack_at=99.99, observed_at=100.0):
    safety.update(
        ready=True,
        stale=False,
        state="DISARMED",
        can_move=False,
        moving=False,
        owner=None,
        generation="stopped-generation",
        reason="operator_stop",
        observed_at=observed_at,
        recent_acks=[
            {
                "accepted": True,
                "source": "manual",
                "action": "stop",
                "status": "executed",
                "reason": "stopped",
                "generation": "stopped-generation",
                "observed_at": ack_at,
            }
        ],
    )
    safety["journey"].update(active=False, state="stopped", reason="operator_stop")


def fail_reference(instance):
    error = urllib.error.HTTPError(
        "http://fixture/vision",
        409,
        "fixture",
        {},
        io.BytesIO(json.dumps({"detail": {"code": "stale_device_session"}}).encode()),
    )

    def failed(*_args):
        raise error

    instance.request = failed
    return {
        "run_id": instance.run_id,
        "sequence": 24,
        "journey": dict(instance.lease.journey.context),
    }


def test_accepted_stop_before_stale_session_reply_preserves_stopped(isolated, monkeypatch):
    instance, safety = runner(isolated)
    monkeypatch.setattr(time, "time", lambda: 100.0)
    meta = fail_reference(instance)
    stopped_snapshot(safety)
    original = instance.lease
    assert instance._request_decision(meta, {"data": {}, "content_type": "application/json"}, instance.clock()) == (
        False,
        None,
    )
    assert instance.operator_lifecycle.last_journey["reason"] == "operator_stop"
    assert instance.operator_lifecycle.last_journey["state"] == "stopped"
    assert instance.policy["mode"] == "observe"
    assert instance.lease is not original
    assert instance.input_failure is None
    assert not instance.closed.is_set()
    assert isolated[-1] == []


def test_stale_session_error_before_stop_is_still_failed(isolated, monkeypatch):
    instance, safety = runner(isolated)
    now = [100.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    meta = fail_reference(instance)
    stopped_snapshot(safety, ack_at=100.01, observed_at=100.02)

    def later_snapshot():
        now[0] = 100.03
        return dict(safety)

    monkeypatch.setattr(navigation, "read_status", later_snapshot)
    with pytest.raises(urllib.error.HTTPError):
        instance._request_decision(meta, {"data": {}, "content_type": "application/json"}, instance.clock())
    assert instance.operator_lifecycle.last_journey["state"] == "failed"
    assert instance.operator_lifecycle.last_journey["reason"] == "navigation_transport_or_input_failed"


@pytest.mark.parametrize("invalid", ["other_journey", "stale", "latched", "future_ack", "nan_ack", "wrong_generation"])
def test_unconfirmed_or_previously_failed_stop_cannot_hide_error(isolated, monkeypatch, invalid):
    instance, safety = runner(isolated)
    monkeypatch.setattr(time, "time", lambda: 100.0)
    meta = fail_reference(instance)
    stopped_snapshot(safety)
    if invalid == "other_journey":
        safety["journey"]["id"] = "other"
    elif invalid == "stale":
        safety["stale"] = True
    elif invalid == "latched":
        instance.lease.halt("decision_timeout")
    elif invalid == "future_ack":
        safety["recent_acks"][0]["observed_at"] = 101.0
    elif invalid == "nan_ack":
        safety["recent_acks"][0]["observed_at"] = float("nan")
    else:
        safety["recent_acks"][0]["generation"] = "other"
    with pytest.raises(urllib.error.HTTPError):
        instance._request_decision(meta, {"data": {}, "content_type": "application/json"}, instance.clock())
    assert instance.operator_lifecycle.last_journey["state"] == "failed"
    if invalid == "latched":
        assert instance.operator_lifecycle.last_journey["reason"] == "decision_timeout"
