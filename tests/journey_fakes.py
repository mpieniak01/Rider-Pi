"""Journey integration helpers; clocks, SDK, transport and services stay isolated."""

from copy import deepcopy

from motion_fakes import command

from apps.compute.decision_lease import DecisionLease
from services.navigation_config import DEFAULT


def policy():
    result = deepcopy(DEFAULT)
    result.update(mode="drive", verified=True, calibration_id="isolated", model_sha256="a" * 64)
    result["perception"]["engine"] = "depth_plane"
    result["avoidance"].update(enabled=True, sweep_verified=True, protocol_version=3, max_turn_pulses=1)
    result["avoidance"]["geometry"]["mode"] = "image"
    return result


def arm(instance, **changes):
    return instance.apply(
        command(
            instance,
            "arm",
            **{
                "request_id": "journey-arm",
                "source": "manual",
                "owner": "navigation",
                "arming_mode": "journey",
                "journey_version": 1,
                "journey_id": "mission",
                "execution_context": "panel",
                "panel_id": "operator",
                "operator_control_version": 1,
                "operator_consent": True,
                "operator_plan": "Isolated continuous journey to STOP",
                **changes,
            },
        )
    )


def goal(instance, clock, **changes):
    return command(
        instance,
        **{
            "source": "navigation",
            "execution_context": "panel",
            "operator_operation_id": "journey-arm",
            "journey_version": 1,
            "journey_id": "mission",
            "decision_deadline_monotonic": clock() + 0.15,
            "decision_feedback_deadline_monotonic": clock() + 0.3,
            "duration": 0.15,
            **changes,
        },
    )


def reply(lease, seq, **changes):
    return {
        "protocol_version": 3,
        "run_id": "journey-run",
        "frame_id": "f" + str(seq),
        "sequence": seq,
        "config_revision": 0,
        "action": "go",
        "state": "clear",
        "clear_count": 3,
        "model_sha256": "a" * 64,
        "valid_for_ms": 200,
        "journey": dict(lease.journey.context),
        "host_session": "host-session",
        "maneuver_clear_count": 3,
        "sectors": {side: {"state": "clear", "coverage_complete": True} for side in ("left", "right")},
        "paths": {side: {"state": "clear", "coverage_complete": True} for side in ("left", "right", "guard")},
        **changes,
    }


def lease_for(instance, clock):
    config = policy()
    generation = instance.gate.generation
    acks = []

    def output(speed, duration, yaw=0):
        row = goal(
            instance,
            clock,
            vx=speed,
            yaw=yaw,
            duration=duration,
            decision_deadline_monotonic=lease.deadline,
            decision_feedback_deadline_monotonic=lease.feedback_deadline,
        )
        row["request_id"] = "goal-" + str(row["seq"])
        result = instance.apply(row)
        acks.append(result)
        if result["status"] not in {"accepted", "executed"}:
            raise RuntimeError(result["reason"])

    def stop():
        instance.apply({"action": "stop", "source": "navigation", "expected_generation": generation})

    lease = DecisionLease(
        config,
        "journey-run",
        output,
        stop,
        clock,
        pause=lambda duration: output(0.0, duration),
        feedback_wait=True,
        steer=lambda side, duration: output(0.1, duration, 0.05 if side == "left" else -0.05),
        journey={"version": 1, "id": "mission", "maneuver_epoch": 0},
    )
    return lease, acks
