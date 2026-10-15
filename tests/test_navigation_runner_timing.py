"""Deterministic replay of serial Pi costs; never open a real camera or BUS."""

import json

import pytest
from test_navigation_runner import isolated  # noqa: F401

from apps.compute import navigation as module


class NoWatchdogThread:
    """Lease.accept checks expiry at HTTP return, without wall-clock races."""

    def __init__(self, **_kwargs):
        pass

    def start(self):
        pass

    def is_alive(self):
        return False


@pytest.mark.parametrize(
    "initial_age_ms,first_rtt_ms,valid_ms,feedback_wait,interframe_wait_ms,expected_moves",
    [
        (20.0, 93.66, 200, True, 0, 2),
        # Production seq4: 94.77 ms source age + 92.29 ms RTT = 187.06 ms.
        # Its next 93.66 ms reply cannot fit after 20 ms local apply + 5 ms
        # status + 5 ms configuration, despite that next frame being fresh.
        (94.77, 92.29, 134, False, 0, 1),
        # The opt-in runner now waits in zero for this next fresh response.
        (94.77, 92.29, 134, True, 0, 2),
        # A scheduler/feed stall beyond the separate 300 ms feedback deadline
        # remains terminal, even if the next image itself has age 120.4 ms.
        (94.77, 92.29, 134, True, 210, 1),
    ],
)
def test_bounded_serial_costs_and_production_short_permit_remain_explicit(
    isolated, monkeypatch, initial_age_ms, first_rtt_ms, valid_ms, feedback_wait, interframe_wait_ms, expected_moves
):
    now = [1000.0]
    _, _, _, _, commands = isolated
    reads, claims, rows, gaps = [], [], [], []
    lease_factory = module.DecisionLease

    def lease(*args, **kwargs):
        # Keep the old default-off replay as an explicit baseline only.
        return lease_factory(*args, **{**kwargs, "feedback_wait": feedback_wait})

    monkeypatch.setattr(module, "DecisionLease", lease)
    monkeypatch.setattr(module.time, "time", lambda: now[0])
    monkeypatch.setattr(module.threading, "Thread", NoWatchdogThread)
    snapshot, selection = module.navigation_config.snapshot, module.selected_executor
    safety, intent = module.read_status, module.read_service_intent

    def delayed(name, delay, callback):
        def call(*args, **kwargs):
            now[0] += delay
            reads.append(name)
            return callback(*args, **kwargs)

        return call

    monkeypatch.setattr(module.navigation_config, "snapshot", delayed("policy", 0.003, snapshot))
    monkeypatch.setattr(module, "selected_executor", delayed("selection", 0.002, selection))
    monkeypatch.setattr(module, "read_status", delayed("safety", 0.004, safety))
    monkeypatch.setattr(module, "read_service_intent", delayed("intent", 0.002, intent))

    def claim(*_args, **kwargs):
        now[0] += 0.012
        claims.append(kwargs)
        return True

    def submit(data, **_kwargs):
        now[0] += 0.002
        commands.append(data)
        return {"ok": True}, 200

    from services import compute_config

    original_write = compute_config._write

    def status_write(target, row):
        original_write(target, row)
        if target.name == "status.json":
            rows.append(json.loads(json.dumps(row)))
            now[0] += 0.005

    monkeypatch.setattr(module, "write_intent_status", claim)
    monkeypatch.setattr(module, "submit_control", submit)
    monkeypatch.setattr(compute_config, "_write", status_write)

    class Source:
        count = 0

        def recv(self, _timeout):
            self.count += 1
            if self.count > 2:
                runner.closed.set()
                return None
            if self.count == 2:
                now[0] += interframe_wait_ms / 1000
            age_ms = initial_age_ms if self.count == 1 else 26.74
            return {
                "input_id": str(self.count),
                "captured_at": now[0] - age_ms / 1000,
                "content_type": "image/jpeg",
                "data": b"replay-fixture",
            }

        def close(self):
            pass

    def remote(meta, *_args):
        now[0] += (first_rtt_ms if meta["sequence"] == 1 else 93.66) / 1000
        if (
            feedback_wait
            and meta["sequence"] == 2
            and now[0] < runner.lease.feedback_deadline
            and now[0] >= runner.lease.deadline
        ):
            assert runner.lease.tick()
            gaps.append((runner.lease.moving, runner.lease.deadline, len(commands)))
        return {
            **{key: meta[key] for key in ("protocol_version", "run_id", "frame_id", "sequence", "config_revision")},
            "action": "go",
            "state": "clear",
            "reason": "depth_plane_candidate",
            "clear_count": meta["sequence"] + 2,
            "valid_for_ms": valid_ms if meta["sequence"] == 1 else 200,
            "model_sha256": "a" * 64,
        }

    runner = module.NavigationRunner(source_factory=Source, request=remote, clock=lambda: now[0])
    assert runner.run() == 0
    moves = [row for row in commands if row["action"] == "move"]
    assert len(moves) == expected_moves
    # One startup binding, then one fresh check per submitted command, and
    # one final inactive claim. No second preflight/claim in a frame iteration.
    assert len(claims) == expected_moves + 2
    assert reads.count("intent") == expected_moves + 1
    assert len({row["run_started_monotonic"] for row in rows}) == 1
    assert runner.run_started_monotonic < rows[-1]["sampled_monotonic"]
    first = next(row for row in rows if (row["decision"] or {}).get("sequence") == 1)
    assert first["cycle_timings_ms"] == pytest.approx(
        {
            "configuration_ms": 5,
            "frame_wait_ms": 0,
            "safety_read_ms": 4,
            "intent_read_ms": 2,
            "producer_claim_ms": 12,
            "authority_ms": 18,
            "submit_ms": 2,
            "decision_apply_ms": 20,
        }
    )
    assert first["previous_status_write_ms"] == pytest.approx(5)
    assert first["request_roundtrip_ms"] == pytest.approx(first_rtt_ms)
    # The executor gets the original capture/decision deadline, without adding
    # the 20 ms spent on fresh authority and submission back to the permit.
    assert moves[0]["decision_deadline_monotonic"] - first["sampled_monotonic"] == pytest.approx(
        first["permit_remaining_ms"] / 1000, abs=0.00001
    )
    if expected_moves == 1:
        assert runner.lease.reason == "decision_timeout"
        assert rows[-1]["decision"]["action"] == "go"
        assert rows[-1]["response_age_ms"] == pytest.approx(120.4)
        assert rows[-1]["latched"]
        assert rows[-1]["permit_remaining_ms"] == 0
        assert commands[-1]["action"] == "stop"
    elif initial_age_ms == 94.77:
        assert gaps == [(False, None, 1)]
        assert moves[1]["ts"] > moves[0]["decision_deadline_monotonic"]
        assert not any(row["action"] == "arm" for row in commands)


@pytest.mark.parametrize("phase", ["recv", "http"])
@pytest.mark.parametrize("change", ["stop", "generation", "settings"])
def test_authority_changed_while_waiting_cannot_submit_move(isolated, monkeypatch, phase, change):
    _, _, safety, _, commands = isolated
    monkeypatch.setattr(module.threading, "Thread", NoWatchdogThread)

    def cancel():
        if change == "stop":
            safety["can_move"] = False
        elif change == "generation":
            safety["generation"] = "new-manual-generation"
            safety["owner"] = "manual"
        else:
            safety["manual_settings"] = {"revision": 4}

    class Source:
        def recv(self, _timeout):
            if phase == "recv":
                cancel()
            return {
                "input_id": "frame",
                "captured_at": module.time.time(),
                "content_type": "image/jpeg",
                "data": b"fixture",
            }

        def close(self):
            pass

    def remote(meta, *_args):
        if phase == "http":
            cancel()
        return {
            **{key: meta[key] for key in ("protocol_version", "run_id", "frame_id", "sequence", "config_revision")},
            "action": "go",
            "state": "clear",
            "clear_count": 3,
            "valid_for_ms": 200,
            "model_sha256": "a" * 64,
        }

    runner = module.NavigationRunner(source_factory=Source, request=remote)
    assert runner.run() == 2
    assert runner.lease.latched
    assert not any(row["action"] == "move" for row in commands)
    if change == "generation":
        assert commands == []  # The old runner cannot stop the new manual owner.


def test_authority_cost_cannot_publish_a_move_after_its_original_deadline(isolated, monkeypatch):
    now = [10.0]
    commands = isolated[-1]

    def slow_claim(*_args, **_kwargs):
        now[0] += 0.08
        return True

    monkeypatch.setattr(module, "write_intent_status", slow_claim)
    runner = module.NavigationRunner(clock=lambda: now[0])
    decision = {
        "protocol_version": 1,
        "run_id": runner.run_id,
        "frame_id": "frame",
        "sequence": 1,
        "config_revision": runner.policy["revision"],
        "action": "go",
        "state": "clear",
        "clear_count": 3,
        "valid_for_ms": 50,
        "model_sha256": "a" * 64,
    }
    with pytest.raises(module.ComputeError) as failure:
        runner.lease.accept(decision, "frame", 1, now[0])
    assert failure.value.code == "navigation_decision_expired_before_submit"
    assert runner.motion_failure["reason"] == "navigation_decision_expired_before_submit"
    assert runner.lease.latched
    assert not runner.lease.moving and runner.lease.deadline is None
    assert not any(row["action"] == "move" for row in commands)
    assert commands[-1]["action"] == "stop"


@pytest.mark.parametrize(
    "reason,exit_code,terminal",
    [
        ("consent_expired", 0, "trial_completed"),
        ("stopped", 2, "navigation_authority_lost"),
    ],
)
def test_actual_timed_consent_expiry_is_completion_but_operator_stop_is_not(
    isolated, monkeypatch, reason, exit_code, terminal
):
    _, _, safety, _, _ = isolated

    class Source:
        def close(self):
            pass

    runner = module.NavigationRunner(source_factory=Source)
    runner.generation = "accepted-original-arm"
    safety.update(state="DISARMED", reason=reason, can_move=False, owner=None)
    assert runner.run() == exit_code
    assert runner.lease.reason == terminal
    assert runner.motion_failure is None


def test_short_permit_reports_zero_and_continues_only_on_next_fresh_frame(isolated, monkeypatch):
    now = [1000.0]
    _, _, _, _, commands = isolated
    rows = []
    monkeypatch.setattr(module.time, "time", lambda: now[0])
    monkeypatch.setattr(module.threading, "Thread", NoWatchdogThread)
    from services import compute_config

    original_write = compute_config._write

    def write(target, row):
        original_write(target, row)
        if target.name == "status.json":
            rows.append(json.loads(json.dumps(row)))

    monkeypatch.setattr(compute_config, "_write", write)

    class Source:
        count = 0

        def recv(self, _timeout):
            self.count += 1
            if self.count > 3:
                runner.closed.set()
                return None
            if self.count == 2:
                now[0] += 0.019914143
            age = {1: 0.02414, 2: 0.04411, 3: 0.020}[self.count]
            return {
                "input_id": str(self.count),
                "captured_at": now[0] - age,
                "content_type": "image/jpeg",
                "data": b"recorded-timing",
            }

        def close(self):
            pass

    def remote(meta, *_):
        seq = meta["sequence"]
        now[0] += {1: 0.06275, 2: 0.25189, 3: 0.060}[seq]
        return {
            **{key: meta[key] for key in ("protocol_version", "run_id", "frame_id", "sequence", "config_revision")},
            "action": "go",
            "vision_action": "go",
            "state": "clear",
            "clear_count": 50,
            "reason": "depth_plane_candidate",
            "valid_for_ms": 181 if seq == 2 else 200,
            "model_sha256": "a" * 64,
        }

    runner = module.NavigationRunner(source_factory=Source, request=remote, clock=lambda: now[0])
    assert runner.run() == 0
    moves = [row for row in commands if row["action"] == "move"]
    assert [row["vx"] for row in moves] == [0.1, 0.0, 0.1]
    paused = next(row for row in rows if (row["decision"] or {}).get("sequence") == 2)
    assert paused["paused"] and not paused["latched"]
    assert paused["decision"]["vision_action"] == "go"
    assert paused["decision"]["action"] == "stop"
    assert paused["stop_reason"] == "awaiting_fresh_decision"
    assert len({row["generation"] for row in moves}) == 1
    assert all(row["duration"] <= 0.15 for row in moves)
