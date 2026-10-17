"""Warm worker transitions share a source and never need new services or UART."""

import time

from test_navigation_runner import isolated as isolated

from apps.compute import navigation as module


def test_intervention_and_resume_keep_one_worker_source_and_three_new_frames(isolated):
    _, _, safety, _, commands = isolated
    safety.update(
        state="ARMED",
        panel_control={"version": 1, "holder": "operator"},
        operator_control={"version": 1, "state": "qualifying", "operation_id": "initial"},
    )
    calls = []
    births = []
    runner = None

    class Source:
        index = 0

        def recv(self, _timeout):
            self.index += 1
            if self.index == 10:
                runner.closed.set()
                return None
            return {
                "input_id": "image-" + str(self.index),
                "captured_at": time.time(),
                "content_type": "image/jpeg",
                "data": b"fixture",
            }

        def close(self):
            calls.append("source-closed")

    source = Source()

    def factory():
        births.append("source")
        return source

    def remote(meta, *_):
        calls.append((source.index, meta["mode"], meta["run_id"]))
        if source.index == 4:
            safety.update(
                owner="manual",
                generation="manual",
                operator_control={
                    "version": 1,
                    "state": "paused",
                    "operation_id": "correction",
                },
            )
        if source.index == 6:
            safety.update(
                owner="navigation",
                generation="resumed",
                operator_control={
                    "version": 1,
                    "state": "qualifying",
                    "operation_id": "resume",
                },
            )
        return {
            **{key: meta[key] for key in ("protocol_version", "run_id", "frame_id", "sequence", "config_revision")},
            "action": "go",
            "state": "clear",
            "clear_count": 900,
            "model_sha256": "a" * 64,
            "valid_for_ms": 150,
        }

    runner = module.NavigationRunner(source_factory=factory, request=remote)
    assert runner.run() == 0
    motions = [row for row in commands if row.get("action") == "move" and row.get("vx")]
    assert len(motions) == 2
    assert [row["generation"] for row in motions] == ["gen", "resumed"]
    assert [row["operator_operation_id"] for row in motions] == ["initial", "resume"]
    assert len({row["request_id"].rsplit("-", 1)[0] for row in motions}) == 2
    assert births == ["source"]
    assert calls[-1] == "source-closed"
    assert next(row for row in calls if isinstance(row, tuple) and row[0] == 5)[1] == "observe"


def test_old_epoch_callback_cannot_submit_under_new_resume_generation(isolated):
    _, _, safety, intent, commands = isolated
    safety.update(
        state="ARMED",
        panel_control={"holder": "operator"},
        operator_control={
            "version": 1,
            "state": "qualifying",
            "operation_id": "first",
        },
    )
    runner = module.NavigationRunner()
    runner._authority()
    safety.update(
        generation="second",
        operator_control={
            "version": 1,
            "state": "qualifying",
            "operation_id": "second",
        },
    )
    runner._authority()
    old = runner.lease
    safety.update(
        generation="third",
        operator_control={
            "version": 1,
            "state": "qualifying",
            "operation_id": "third",
        },
    )
    runner._authority()
    import pytest

    from apps.compute.client import ComputeError

    with pytest.raises(ComputeError, match="navigation_operation_stale"):
        old.drive(0.1, 0.1)
    assert commands == []


def test_old_lease_halt_and_tick_cannot_stop_new_epoch(isolated):
    _, _, safety, _, commands = isolated
    safety.update(
        state="ARMED",
        panel_control={"holder": "operator"},
        operator_control={
            "version": 1,
            "state": "qualifying",
            "operation_id": "first",
        },
    )
    runner = module.NavigationRunner()
    runner._authority()
    old = runner.lease
    safety.update(
        generation="next",
        operator_control={
            "version": 1,
            "state": "qualifying",
            "operation_id": "next",
        },
    )
    runner._authority()
    old.halt("old_timeout")
    old.tick()
    assert commands == []
    assert not runner.lease.latched
