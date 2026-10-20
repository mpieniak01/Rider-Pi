"""Deterministic replay of serial Pi costs; never open a real camera or BUS."""

import io
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
    assert not runner.lease.moving
    assert runner.lease.deadline is None
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
    assert paused["paused"]
    assert not paused["latched"]
    assert paused["decision"]["vision_action"] == "go"
    assert paused["decision"]["action"] == "stop"
    assert paused["stop_reason"] == "awaiting_fresh_decision"
    assert len({row["generation"] for row in moves}) == 1
    assert all(row["duration"] <= 0.15 for row in moves)


@pytest.mark.parametrize("maneuver_protocol", [2, 3])
def test_post_turn_capture_gate_rejects_forward_from_old_orientation(isolated, monkeypatch, maneuver_protocol):
    policy, _, _, _, commands = isolated
    policy["avoidance"] = {
        **policy["avoidance"],
        "enabled": True,
        "sweep_verified": True,
        "protocol_version": maneuver_protocol,
    }
    policy["avoidance"]["geometry"] = {**policy["avoidance"]["geometry"], "mode": "image"}
    now = [1000.0]
    phases = []
    monkeypatch.setattr(module.time, "time", lambda: now[0])
    monkeypatch.setattr(module.threading, "Thread", NoWatchdogThread)

    class Source:
        count = 0

        def recv(self, _timeout):
            self.count += 1
            if self.count > 9:
                runner.closed.set()
                return None
            now[0] = 1000.0 + self.count * 0.05
            return {
                "input_id": str(self.count),
                "captured_at": now[0],
                "content_type": "image/jpeg",
                "data": b"recorded-frame",
            }

        def close(self):
            pass

    def remote(meta, *_):
        assert meta["protocol_version"] == maneuver_protocol
        phases.append(meta["motion_phase"])
        return {
            **{key: meta[key] for key in ("protocol_version", "run_id", "frame_id", "sequence", "config_revision")},
            "action": "stop"
            if meta["sequence"] == 1
            else ("turn_left" if maneuver_protocol == 2 else "steer_left")
            if meta["sequence"] == 2
            else "go",
            "state": "obstacle" if meta["sequence"] < 3 else "clear",
            "reason": "depth_ground_deviation",
            "clear_count": 3,
            "valid_for_ms": 200,
            "model_sha256": "a" * 64,
            "farther_outlier_pixels": 0,
            "maneuver_clear_count": 3,
            "sectors": {"left": {"state": "clear", "coverage_complete": True}},
            "paths": {
                "left": {"state": "clear", "coverage_complete": True},
                "guard": {"state": "clear", "coverage_complete": True},
            },
        }

    runner = module.NavigationRunner(source_factory=Source, request=remote, clock=lambda: now[0])
    runner.run()
    turns = [row for row in commands if row.get("yaw", 0)]
    forwards = [row for row in commands if row.get("vx", 0) and not row.get("yaw", 0)]
    assert len(turns) == 1
    assert len(forwards) == 1
    if maneuver_protocol == 2:
        assert phases[2:7] == ["turn_settling"] * 5
    else:
        assert phases[2:7] == ["steer_wait"] * 5
    assert phases[-1] == "ready"
    assert commands[-1]["action"] == "stop"


def test_pending_steer_capture_waits_for_lease_not_submission_duration(isolated, monkeypatch):
    policy, _, _, _, commands = isolated
    policy["avoidance"] = {**policy["avoidance"], "protocol_version": 3, "enabled": True, "sweep_verified": True}
    runner = module.NavigationRunner()
    runner.motion_publisher = object()
    runner.lease.deadline = runner.clock() + 0.2
    deadline = runner.lease.deadline

    def pending(body, **kwargs):
        assert kwargs["timeout_s"] == 0.0
        commands.append(body)
        return {"pending": True}, 202

    monkeypatch.setattr(module, "submit_control", pending)
    runner.steer("left", 0.05)
    assert runner.pending_motion_acks
    assert commands[-1]["decision_deadline_monotonic"] == deadline
    assert runner.turn_capture_after == deadline + 0.1
    assert runner.lease.deadline == deadline


@pytest.mark.parametrize(
    "response_age_ms,changed_source,expected_moves",
    [
        (247.29, None, 2),
        (300.0, None, 1),
        (300.01, None, 1),
        (247.29, "transport_epoch", 1),
        (247.29, "sha256", 1),
    ],
)
def test_native_reference_recorded_delay_retains_original_capture_deadline(
    isolated, monkeypatch, response_age_ms, changed_source, expected_moves
):
    # Real native trial: 46.88 ms before POST + 200.41 ms RTT = 247.29 ms.
    # The corrected host reply is usable, but Pi still permits only 52.71 ms.
    from apps.compute import stream_prepare

    _, _, _, _, commands = isolated
    now_ns = [1_000_000_000]
    captures, requests = [], []
    monkeypatch.setattr(module.time, "time", lambda: now_ns[0] / 1_000_000_000)
    monkeypatch.setattr(module.threading, "Thread", NoWatchdogThread)
    # Transport preparation is tested separately; this replay opens no socket.
    monkeypatch.setattr(stream_prepare, "prepare_stream", lambda **_kwargs: None)

    class Source:
        count = 0

        def recv(self, _timeout):
            self.count += 1
            if self.count > 2:
                runner.closed.set()
                return None
            age_ns = 63_420_000 if self.count == 1 else 46_880_000
            captured_ns = now_ns[0] - age_ns
            captures.append(captured_ns)
            sequence = 78 if self.count == 1 else 80
            source = {
                "camera_session": "recorded-native-session",
                "sequence": sequence,
                "transport_epoch": 39,
                "pipeline_revision": 28,
                "frame_id": f"recorded-native-session-{sequence}",
                "sha256": ("b" if self.count == 1 else "c") * 64,
            }
            return {
                "input_id": source["frame_id"],
                "captured_at": captured_ns / 1_000_000_000,
                "captured_monotonic_ns": captured_ns,
                "content_type": "application/json",
                "data": source,
            }

        def close(self):
            pass

    class Opener:
        def open(self, req, *, timeout):
            assert req.full_url.endswith("/vision/decision-reference")
            assert req.get_method() == "POST"
            assert timeout == pytest.approx(0.3)
            payload = json.loads(req.data)
            meta, source = payload["frame"], payload["source"]
            assert meta["frame_id"] != source["frame_id"]
            assert meta["sequence"] != source["sequence"]
            assert meta["deadline_ms"] == 300
            if meta["sequence"] == 1:
                # The preceding real GO had age 142.56 ms and a 121 ms permit.
                now_ns[0] += 79_140_000
            else:
                assert meta["age_ms"] == pytest.approx(46.88)
                now_ns[0] = captures[-1] + round(response_age_ms * 1_000_000)
            requests.append(payload)
            echoed_source = dict(source)
            if meta["sequence"] == 2 and changed_source:
                echoed_source[changed_source] = 40 if changed_source == "transport_epoch" else "d" * 64
            return io.BytesIO(
                json.dumps(
                    {
                        **{
                            key: meta[key]
                            for key in ("protocol_version", "run_id", "frame_id", "sequence", "config_revision")
                        },
                        "source": echoed_source,
                        "action": "go",
                        "state": "clear",
                        "reason": "depth_plane_candidate",
                        "clear_count": 4,
                        "valid_for_ms": 121 if meta["sequence"] == 1 else 200,
                        "model_sha256": "a" * 64,
                    }
                ).encode()
            )

        def close(self):
            pass

    monkeypatch.setattr(module, "NavigationHTTPTransport", lambda *_args, **kw: Opener())
    runner = module.NavigationRunner(source_factory=Source, clock=lambda: now_ns[0] / 1_000_000_000)
    assert runner.run() == (2 if changed_source else 0)
    assert len(requests) == 2
    moves = [row for row in commands if row["action"] == "move" and row["vx"] > 0]
    assert len(moves) == expected_moves
    assert commands[-1]["action"] == "stop"
    assert not any(row["action"] == "arm" for row in commands)
    assert moves[0]["duration"] == pytest.approx(0.121)
    if changed_source:
        assert runner.lease.reason == "navigation_reference_mismatch"
        return
    decision = next(row for row in runner.decision_trace if (row["decision"] or {}).get("sequence") == 2)
    assert decision["response_age_ms"] == pytest.approx(response_age_ms)
    if response_age_ms < 300:
        assert decision["request_roundtrip_ms"] == pytest.approx(200.41)
        assert decision["decision"]["valid_for_ms"] == 200
        assert not decision["latched"]
        assert not decision["paused"]
        assert decision["permit_remaining_ms"] == pytest.approx(52.71)
        move = moves[-1]
        assert move["duration"] == pytest.approx(0.05271)
        assert move["decision_deadline_monotonic"] == pytest.approx(captures[-1] / 1_000_000_000 + 0.3)
        assert move["ts"] + move["duration"] == pytest.approx(move["decision_deadline_monotonic"])
    else:
        # Even a matching, positive host permit cannot renew an expired capture.
        assert decision["latched"]
        assert decision["permit_remaining_ms"] == 0
        assert runner.lease.reason == "decision_invalid_or_expired"
