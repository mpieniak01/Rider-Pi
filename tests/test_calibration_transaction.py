"""Durable activation boundaries; every adapter/clock/store is isolated."""

import pytest
from motion_fakes import arm, executor as executor
from test_calibration_runtime import activate, estimate, isolated_store as isolated_store

from apps.motion import calibration_profiles as profiles
from apps.motion.calibration_runtime import CalibrationRuntime


@pytest.mark.parametrize("failure", ["estop", "ttl", "pending", "target", "generation"])
def test_rejected_precommit_never_boot_loads_staged_profile(executor, monkeypatch, failure):
    instance, clock = executor
    stage = profiles.write_active

    def changed(*args, **kwargs):
        pointer = stage(*args, **kwargs)
        if failure == "estop":
            instance.gate.latch_estop(persist=False)
        elif failure == "ttl":
            clock.now += 0.6
        elif failure == "pending":
            instance.pending = {"request_id": "unexpected-goal"}
        elif failure == "target":
            instance.controller.t_lx = 0.01
        else:
            instance.gate.disarm("changed_generation")
        return pointer

    monkeypatch.setattr(profiles, "write_active", changed)
    before = list(instance.adapter.calls)
    old_limits = instance.controller.limits
    ack = activate(instance)
    assert ack["status"] == "rejected" and ack["error"] == "calibration_state_changed_during_apply"
    assert instance.controller.limits == old_limits and instance.adapter.calls == before
    pointer = profiles.read_active(include_pending=True)
    assert pointer["activation_state"] == "pending" and pointer["profile_digest"] == ack["profile_digest"]
    with pytest.raises(ValueError, match="active_profile_pending"):
        profiles.read_active()
    restored = CalibrationRuntime(old_limits)
    assert restored.error and restored.profile_digest is None and restored.limits == old_limits
    estimator = estimate(clock)
    assert estimator.calibration_state()["error"] and not estimator.reference_verified
    assert not estimator.get_pose()["data_ready"]


def test_final_commit_failure_inhibits_current_arm_and_next_boot(executor, monkeypatch):
    instance, clock = executor
    before = list(instance.adapter.calls)
    previous_generation = instance.gate.generation

    def failed(*_args, **_kwargs):
        raise OSError("fake final commit failure")

    monkeypatch.setattr(profiles, "commit_active", failed)
    ack = activate(instance)
    assert ack["status"] == "rejected" and ack["error"] == "calibration_commit_failed:OSError"
    assert instance.calibration.error == ack["error"]
    assert instance.gate.state == "DISARMED" and instance.gate.generation != previous_generation
    assert instance.controller.limits.speed_limit == 0.4  # actual logical application is visible
    assert not instance.snapshot()["ready"] and not arm(instance)["accepted"]
    assert instance.calibration.applied_ack is None and instance.adapter.calls == before
    assert profiles.read_active(include_pending=True)["activation_state"] == "pending"
    restored = CalibrationRuntime(instance.calibration.ceilings)
    assert restored.error and restored.profile_digest is None
    estimator = estimate(clock)
    estimator.update_executor_state(instance.snapshot())
    assert estimator.calibration_state()["error"] and not estimator.calibration_state()["model_ready"]


def test_estop_during_final_commit_is_later_than_software_acceptance(executor, monkeypatch):
    instance, clock = executor
    commit = profiles.commit_active

    def later_estop(*args, **kwargs):
        instance.gate.latch_estop(persist=False)
        return commit(*args, **kwargs)

    monkeypatch.setattr(profiles, "commit_active", later_estop)
    before = list(instance.adapter.calls)
    ack = activate(instance)
    assert ack["status"] == "executed" and ack["accepted"] and ack["actuation"] is False
    assert ack["generation"] == instance.calibration.applied_generation != instance.gate.generation
    assert instance.gate.state == "ESTOP" and not instance.snapshot()["can_move"]
    assert instance.adapter.calls == before
    assert profiles.read_active()["activation_state"] == "applied"
    assert instance.calibration.applied_ack == ack and instance.calibration.error is None
    restored = CalibrationRuntime(instance.calibration.ceilings)
    assert restored.source == "saved_profile" and restored.profile_digest == ack["profile_digest"]
    assert restored.applied_ack is None and restored.applied_generation is None
    estimator = estimate(clock)
    estimator.update_executor_state(instance.snapshot())
    assert estimator.calibration_state()["error"] == "calibration_requires_idle_disarmed"


def test_successful_two_phase_activation_confirms_consumers_without_sdk(executor):
    instance, clock = executor
    before = list(instance.adapter.calls)
    ack = activate(instance)
    assert ack["status"] == "executed"
    pointer = profiles.read_active()
    assert pointer["activation_state"] == "applied"
    assert pointer["profile_digest"] == instance.calibration.profile_digest == ack["profile_digest"]
    assert pointer["command_generation"] == ack["command_generation"]
    assert instance.adapter.calls == before
    estimator = estimate(clock)
    estimator.update_executor_state(instance.snapshot())
    config = estimator.calibration_state()
    assert config["error"] is None and config["profile_digest"] == pointer["profile_digest"]
    assert config["applied_generation"] == ack["generation"]
    assert config["activation_request_id"] == pointer["request_id"]
    assert not estimator.reference_verified and not config["model_ready"]


def test_explicit_reapply_recovers_uncommitted_pointer(executor, monkeypatch):
    instance, _ = executor
    commit = profiles.commit_active

    def failed(*_args, **_kwargs):
        raise OSError("fake commit failure")

    monkeypatch.setattr(profiles, "commit_active", failed)
    failed_ack = activate(instance)
    assert not failed_ack["accepted"] and instance.calibration.error
    monkeypatch.setattr(profiles, "commit_active", commit)
    before = list(instance.adapter.calls)
    ack = activate(instance, failed_ack["profile_digest"])
    assert ack["accepted"] and instance.calibration.error is None
    assert profiles.read_active()["activation_state"] == "applied"
    assert instance.adapter.calls == before and instance.gate.state == "DISARMED"
