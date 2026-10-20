"""Terminal mission authority ends while its producer can remain observation-only."""

import pytest
from journey_fakes import policy
from test_navigation_runner import isolated as isolated

from apps.compute import navigation
from apps.compute.client import ComputeError


def runner(isolated):
    config, _, safety, _, _ = isolated
    config.update(policy())
    safety.update(
        arming_mode="journey",
        navigation_journey_version=1,
        journey={"version": 1, "id": "mission", "active": True, "state": "qualifying", "reason": "qualified"},
        state="ARMED",
        panel_control={"holder": "operator"},
        operator_control={"version": 1, "state": "qualifying", "operation_id": "first"},
    )
    result = navigation.NavigationRunner()
    assert result._authority()
    return result, safety


@pytest.mark.parametrize(
    "change",
    [
        {"state": "DISARMED", "can_move": False},
        {"owner": "manual", "generation": "manual"},
        {"generation": "replacement"},
        {"operator_control": {"version": 1, "state": "qualifying", "operation_id": "new"}},
        {"journey": {"version": 1, "id": "other", "active": True}},
    ],
)
def test_authority_change_ends_old_journey_but_preserves_observation(isolated, change):
    instance, safety = runner(isolated)
    identity = instance.run_id
    original = instance.lease
    safety.update(change)
    assert instance._authority() is False
    assert instance.policy["mode"] == "observe"
    assert instance.lease is not original
    assert original.journey.active is False
    assert instance.run_id != identity
    assert instance.operator_lifecycle.last_journey["id"] == "mission"
    assert instance._authority() is False  # Same old intent/ARM never resumes.
    assert all(row["action"] == "stop" for row in isolated[-1])


def test_journey_metadata_is_drive_only_and_status_preserves_terminal_result(isolated, monkeypatch, tmp_path):
    import json

    instance, _ = runner(isolated)
    instance.last_frame = ("frame", 100)
    _, meta = instance._frame_metadata(0)
    assert meta["journey"] == {"version": 1, "id": "mission", "maneuver_epoch": 0}
    instance.policy["mode"] = "observe"
    _, observed = instance._frame_metadata(0)
    assert "journey" not in observed
    instance.policy["mode"] = "drive"
    instance.lease.halt("operator_stop")
    instance.closed.set()
    target = tmp_path / "last.json"
    monkeypatch.setenv("RIDER_NAVIGATION_STATUS", str(target))
    instance._status(None)
    result = json.loads(target.read_text())
    assert result["journey"]["id"] == "mission"
    assert result["journey"]["active"] is False
    assert result["journey"]["state"] == "stopped"
    assert result["running"] is False
    assert result["journey"]["maneuver_epoch"] == 0
    assert (tmp_path / "navigation_trial.json").is_file()


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"manual_settings": {"revision": 4}}, "navigation_settings_stale"),
        ({"calibration": {"profile_digest": "new-calibration"}}, "navigation_calibration_changed"),
        ({"remote_decision_feedback_supported": False}, "navigation_executor_update_required"),
    ],
)
def test_active_journey_rechecks_executor_calibration_and_settings(isolated, change, reason):
    instance, safety = runner(isolated)
    safety.update(change)
    with pytest.raises(ComputeError, match=reason):
        instance._authority()
    assert isolated[-1] == []


def test_active_journey_does_not_ignore_rejected_ack_after_go(isolated):
    instance, safety = runner(isolated)
    instance.lease.deadline = instance.clock() + 0.15
    instance.lease.feedback_deadline = instance.clock() + 0.3
    instance.drive(0.1, 0.1)
    assert isolated[-1][-1]["action"] == "move"
    safety["last_ack"] = {
        "request_id": instance.run_id + "-" + str(instance.motion_sequence),
        "status": "rejected",
        "error": "hardware_unavailable",
    }
    with pytest.raises(ComputeError, match="navigation_motion_rejected"):
        instance._authority()
    assert instance.motion_failure["reason"] == "hardware_unavailable"
    instance._run_failure(ComputeError("navigation_motion_rejected"))
    assert not instance.lease.journey.active
    assert instance.lease.latched
    assert isolated[-1][-1]["action"] == "stop"


def test_active_journey_pending_ack_timeout_is_terminal_after_100ms(isolated):
    instance, _ = runner(isolated)
    now = [0.0]
    instance.clock = lambda: now[0]
    instance.pending_motion_acks[instance.run_id + "-1"] = 0.1
    now[0] = 0.11
    with pytest.raises(ComputeError, match="navigation_motion_ack_timeout"):
        instance._authority()
    instance._run_failure(ComputeError("navigation_motion_ack_timeout"))
    assert instance.motion_failure["reason"] == "navigation_motion_ack_timeout"
    assert instance.lease.latched
    assert not instance.lease.journey.active
    assert isolated[-1][-1]["action"] == "stop"


def test_active_journey_cannot_continue_after_feature_intent_replaced(isolated):
    instance, _ = runner(isolated)
    isolated[3]["request_id"] = "replacement"
    with pytest.raises(ComputeError, match="navigation_intent_changed"):
        instance._authority()
    assert isolated[-1] == []
