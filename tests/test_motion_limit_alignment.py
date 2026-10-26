"""New ceilings across policy, settings and executor; fake adapter only."""

from copy import deepcopy

import pytest
from motion_fakes import arm, command, executor as executor
from test_decision_lease import decision, make
from test_held_motion import navigation_arm, navigation_pulse

from apps.motion import manual_settings
from services.navigation_config import DEFAULT, validate


def test_manual_schema_accepts_half_second_and_rejects_longer(tmp_path, monkeypatch):
    monkeypatch.setenv("RIDER_MANUAL_SETTINGS_PATH", str(tmp_path / "settings.json"))
    before = manual_settings.read()
    assert manual_settings.snapshot()["parameter_schema"]["direction_fields"]["duration"]["maximum"] == 0.5
    saved = manual_settings.update(
        {}, before["revision"], directions={"forward": {"speed": 1, "maximum": 1, "duration": 0.5}}
    )
    assert saved["directions"]["forward"]["speed"] == 1
    with pytest.raises(ValueError):
        manual_settings.update({}, saved["revision"], directions={"forward": {"duration": 0.501}})
    assert manual_settings.read() == saved


def test_avoidance_accepts_full_scale_without_changing_default_settings():
    policy = deepcopy(DEFAULT)
    policy.update(speed=1, max_motion_ms=500)
    policy["perception"]["engine"] = "depth_plane"
    policy["avoidance"].update(enabled=True, turn_speed=1, turn_ms=500)
    assert validate(policy)["speed"] == 1
    assert DEFAULT["speed"] == 0.1
    for field, value in [("speed", 1.001), ("max_motion_ms", 501)]:
        with pytest.raises(ValueError):
            validate({**policy, field: value})
    for field, value in [("turn_speed", 1.001), ("turn_ms", 501)]:
        invalid = deepcopy(policy)
        invalid["avoidance"][field] = value
        with pytest.raises(ValueError):
            validate(invalid)


def test_five_hundred_ms_reply_can_move_but_never_survive_its_deadline():
    lease, now, calls = make()
    lease.config.update(speed=1, max_motion_ms=500, decision_budget_ms=500)
    assert lease.accept(decision(valid_for_ms=500), "f1", 1, 0)
    assert calls[-1] == ("go", 1, 0.5)
    now[0] = 0.501
    assert not lease.tick()
    assert calls[-1] == ("stop",)


def test_longer_reply_rejected_and_capture_age_still_shortens_motion():
    lease, now, calls = make()
    lease.config.update(max_motion_ms=500, decision_budget_ms=500)
    now[0] = 0.2
    assert lease.accept(decision(valid_for_ms=500), "f1", 1, 0)
    assert calls[-1][2] == pytest.approx(0.3)
    other, _, output = make()
    assert not other.accept(decision(valid_for_ms=501), "f1", 1, 0)
    assert not any(row[0] == "go" for row in output)


def test_executor_accepts_half_second_and_rejects_one_ms_more(executor):
    instance, clock = executor
    assert arm(instance)["status"] == "executed"
    row = manual_settings.read()
    manual_settings.update({}, row["revision"], directions={"forward": {"duration": 0.5}})
    ack = instance.apply(command(instance, duration=0.5))
    assert ack["status"] == "accepted", ack
    assert instance.controller.deadline == clock.now + 0.5
    assert instance.apply(command(instance, duration=0.501))["status"] == "rejected"


def test_navigation_uses_its_own_pulse_not_the_manual_preset(executor):
    instance, clock = executor
    before = manual_settings.read()
    navigation_arm(instance)
    payload = navigation_pulse(instance, clock)
    payload.update(vx=1, duration=0.5, decision_deadline_monotonic=clock.now + 0.5)
    ack = instance.apply(payload)
    assert ack["status"] == "accepted", ack
    assert instance.controller.t_lx == 1
    assert instance.controller.deadline == clock.now + 0.5
    assert manual_settings.read() == before
    # The same full-scale value still cannot bypass a manual profile ceiling.
    instance.apply(command(instance, "stop"))
    assert arm(instance)["status"] == "executed"
    ack = instance.apply(command(instance, vx=1, duration=0.5))
    assert ack["status"] == "rejected"
