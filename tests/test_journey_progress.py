"""Maneuver reset requires fresh Pi-confirmed progress, never elapsed time."""

import pytest
from journey_fakes import policy, reply

from apps.compute.decision_lease import DecisionLease


def setup():
    now, calls = [0.0], []
    lease = DecisionLease(
        policy(),
        "journey-run",
        lambda *x: calls.append(("go", *x)),
        lambda: calls.append(("stop",)),
        lambda: now[0],
        pause=lambda *x: calls.append(("zero", *x)),
        feedback_wait=True,
        steer=lambda *x: calls.append(("steer", *x)),
        journey={"version": 1, "id": "mission", "maneuver_epoch": 0},
    )
    return lease, now, calls


def accept(lease, now, sequence, **changes):
    row = reply(lease, sequence, **changes)
    return lease.accept(row, row["frame_id"], sequence, now[0])


def test_two_independent_obstacles_reset_budget_only_after_three_post_settle_go():
    lease, now, calls = setup()
    assert accept(lease, now, 1, state="obstacle", action="steer_left")
    assert lease.turn_count == 1
    now[0] = 0.1
    assert not accept(lease, now, 2, action="stop", state="clear")
    assert lease.turn_count == 1
    assert lease.journey.context["maneuver_epoch"] == 0
    for sequence in (3, 4, 5):
        now[0] = 0.2 + sequence * 0.05
        assert accept(lease, now, sequence)
        assert lease.journey.context["maneuver_epoch"] == (1 if sequence == 5 else 0)
    assert lease.turn_count == 0
    assert accept(lease, now, 6, state="obstacle", action="steer_right")
    assert lease.turn_count == 1
    now[0] = 0.65
    assert not accept(lease, now, 7, action="stop", state="clear")
    for sequence in (8, 9, 10):
        now[0] = 0.8 + (sequence - 8) * 0.1
        assert accept(lease, now, sequence)
    assert lease.turn_count == 0
    assert lease.journey.context["maneuver_epoch"] == 2
    assert [row[1] for row in calls if row[0] == "steer"] == ["left", "right"]


def test_clear_before_settle_and_stop_between_clear_replies_do_not_reset_budget():
    lease, now, _ = setup()
    assert accept(lease, now, 1, state="obstacle", action="steer_left")
    for seq in (2, 3, 4):
        now[0] = seq * 0.02
        assert accept(lease, now, seq)
    assert lease.turn_count == 1
    assert lease.journey.context["maneuver_epoch"] == 0
    now[0] = 0.3
    assert accept(lease, now, 5)
    now[0] += 0.1
    assert not accept(lease, now, 6, state="obstacle", action="stop")
    for seq in (7, 8):
        now[0] += 0.1
        assert accept(lease, now, seq)
        assert lease.turn_count == 1
    now[0] += 0.1
    assert accept(lease, now, 9)
    assert lease.turn_count == 0
    assert lease.journey.context["maneuver_epoch"] == 1


def test_repeated_unsuccessful_steering_is_terminal_without_clearing_budget():
    lease, now, calls = setup()
    assert accept(lease, now, 1, state="obstacle", action="steer_left")
    now[0] = 0.1
    assert not accept(lease, now, 2, state="obstacle", action="steer_left")
    assert lease.latched
    assert lease.journey.snapshot()["state"] == "blocked"
    assert not accept(lease, now, 3)
    assert len([row for row in calls if row[0] == "steer"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"journey": None},
        {"journey": {"version": True, "id": "mission", "maneuver_epoch": 0}},
        {"journey": {"version": 1, "id": "other", "maneuver_epoch": 0}},
        {"journey": {"version": 1, "id": "mission", "maneuver_epoch": 1}},
        {"journey": {"version": 1, "id": "mission", "maneuver_epoch": False}},
        {"host_session": None},
    ],
)
def test_foreign_or_unmatched_journey_metadata_is_terminal(change):
    lease, now, calls = setup()
    assert not accept(lease, now, 1, **change)
    assert lease.latched
    assert calls == [("stop",)]


def test_host_restart_cannot_revive_existing_mission():
    lease, now, calls = setup()
    assert accept(lease, now, 1)
    now[0] = 0.1
    assert not accept(lease, now, 2, host_session="new-process")
    assert lease.latched
    assert lease.reason == "navigation_journey_identity_mismatch"
    assert len([row for row in calls if row[0] == "go"]) == 1


def test_rollback_of_echo_epoch_after_confirmed_progress_is_terminal():
    lease, now, _ = setup()
    assert accept(lease, now, 1, state="obstacle", action="steer_left")
    now[0] = 0.1
    assert not accept(lease, now, 2, action="stop", state="clear")
    for seq in (3, 4, 5):
        now[0] = 0.2 + seq * 0.05
        assert accept(lease, now, seq)
    assert lease.journey.context["maneuver_epoch"] == 1
    now[0] += 0.1
    assert not accept(lease, now, 6, journey={"version": 1, "id": "mission", "maneuver_epoch": 0})
    assert lease.latched


@pytest.mark.parametrize("field", ["device_id", "camera_session", "transport_epoch", "pipeline_revision"])
def test_changed_camera_or_transport_ends_journey_instead_of_requalifying(field):
    lease, now, calls = setup()
    source = {"device_id": "pi", "camera_session": "camera", "transport_epoch": 1, "pipeline_revision": 2}
    assert accept(lease, now, 1, source=source)
    now[0] = 0.1
    assert not accept(lease, now, 2, source={**source, field: "changed"})
    assert lease.latched
    assert len([row for row in calls if row[0] == "go"]) == 1


@pytest.mark.parametrize("field", ["camera_session", "transport_epoch", "pipeline_revision"])
def test_changed_pi_capture_identity_is_detected_before_calling_host(field):
    lease, _, _ = setup()
    source = {"camera_session": "camera", "transport_epoch": 1, "pipeline_revision": 2}
    assert lease.journey.validate_capture({"source": source})
    assert lease.journey.validate_capture({"source": dict(source)})
    assert not lease.journey.validate_capture({"source": {**source, field: "changed"}})
