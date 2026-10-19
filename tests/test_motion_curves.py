"""Curve tests: fake adapters and private files only."""

import pytest
from motion_fakes import executor as executor
from test_held_motion import advance, intent
from test_manual_settings import operator_arm

from apps.motion import manual_settings as settings
from apps.motion.dynamics import CurveRamp, approach, curve_fraction


@pytest.mark.parametrize("mode", [0, 1, 2])
@pytest.mark.parametrize("target", [-0.6, 0.6])
def test_curves_reach_target_and_obey_rate(mode, target):
    ramp = CurveRamp()
    value = 0
    outputs = []
    for _ in range(400):
        previous = value
        value = ramp.step(value, target, 0.5, 0.02, mode)
        assert abs(value - previous) <= 0.5 * 0.02 + 1e-12
        assert min(0, target) <= value <= max(0, target)
        outputs.append(value)
    assert outputs[-1] == pytest.approx(target)
    if mode == 0:
        assert outputs[0] == approach(0, target, 0.5, 0.02)


def test_s_is_gentle_at_both_ends_log_has_fast_start():
    epsilon = 0.001
    assert curve_fraction(1, epsilon) < epsilon / 100
    assert 1 - curve_fraction(1, 1 - epsilon) < epsilon / 100
    assert curve_fraction(2, epsilon) > epsilon


@pytest.mark.parametrize("mode", [1, 2])
def test_hold_renewals_stop_and_pulse_deadline(executor, mode):
    instance, clock = executor
    row = settings.read()
    settings.update({"ramp_mode": mode}, row["revision"])
    operator_arm(instance)
    for _ in range(10):
        assert instance.apply(intent(instance))["status"] == "accepted"
        advance(instance, clock, 0.16)
    assert instance.controller.o_lx == pytest.approx(settings.read()["directions"]["forward"]["speed"])
    instance.controller.stop()
    assert instance.controller.o_lx == 0
    assert all(c.plan is None for c in instance.controller.curves)
    instance.apply(intent(instance, "pulse"))
    advance(instance, clock, 0.3)
    assert instance.controller.stopped
    assert instance.gate.state == "ARMED"


@pytest.mark.parametrize("mode", [1, 2])
def test_release_reversal_bounded_and_no_automatic_disarm(executor, mode):
    instance, clock = executor
    row = settings.read()
    settings.update({"ramp_mode": mode}, row["revision"])
    operator_arm(instance)
    for _ in range(6):
        instance.apply(intent(instance))
        advance(instance, clock, 0.16)
    before = instance.controller.o_lx
    instance.apply(intent(instance, "release"))
    advance(instance, clock, 0.02)
    assert 0 <= instance.controller.o_lx <= before
    advance(instance, clock, 0.5)
    assert instance.controller.o_lx == 0
    assert instance.gate.state == "ARMED"
    for _ in range(6):
        instance.apply(intent(instance, direction="backward"))
        advance(instance, clock, 0.16)
    assert instance.controller.o_lx < 0


def test_migration_profiles_and_reject_unknown_mode(executor):
    instance, _ = executor
    row = settings.read()
    old = dict(row)
    old["values"] = {k: v for k, v in row["values"].items() if k != "ramp_mode"}
    assert settings._canonical(old)["values"]["ramp_mode"] == 0
    row = settings.update({"ramp_mode": 1}, row["revision"])
    row = settings.manage_profile({"action": "create", "name": "Łagodny"}, row["revision"])
    profile_id = row["active_profile"]
    row = settings.update({"ramp_mode": 2}, row["revision"])
    row = settings.manage_profile({"action": "apply", "id": profile_id}, row["revision"])
    assert row["values"]["ramp_mode"] == 1
    with pytest.raises(ValueError, match="ramp_mode"):
        settings.update({"ramp_mode": 3}, row["revision"])
