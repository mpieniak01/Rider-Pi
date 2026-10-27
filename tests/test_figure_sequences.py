"""Own recipes run solely on fake time/adapters; no robot, UART or GPIO."""

import copy
import json

import pytest
from flask import Flask
from motion_fakes import command, executor as executor
from test_held_motion import advance, intent

from apps.motion import manual_settings
from apps.motion.figure_recipes import NAMES, catalog, compile_recipe
from services.api_core import figures_api


def prepare(instance):
    instance.adapter.set_roll = lambda value: instance.adapter.calls.append(("roll", value)) or True


def start(instance, identifier="forward_backward", **changes):
    prepare(instance)
    payload = command(
        instance,
        "arm",
        request_id="figure-" + identifier,
        owner="manual",
        arming_mode="operator",
        execution_context="panel",
        panel_id="figures-panel",
        operator_consent=True,
        operator_plan="Mock-only own figure; no physical robot",
        figure_id=identifier,
        figure_version=1,
    )
    for key in ("vx", "yaw", "duration"):
        payload.pop(key)
    payload.update(changes)
    return payload, instance.apply(payload)


def keepalive(instance, payload):
    body = copy.deepcopy(payload)
    body.update(
        request_id="keep-" + str(instance.gate.clock()),
        figure_run_id=payload["request_id"],
        ts=instance.gate.wall_clock(),
        seq=instance.gate.last_seq + 1,
        generation=instance.gate.generation,
    )
    return instance.apply(body)


def run(instance, clock, payload, seconds):
    for index in range(round(seconds / 0.02)):
        if index % 8 == 0 and instance.figures.active:
            assert keepalive(instance, payload)["status"] == "executed"
        advance(instance, clock, 0.02)


@pytest.mark.parametrize("identifier", list(NAMES))
def test_each_own_recipe_finishes_zero_and_disarmed_without_native_actions(executor, identifier):
    instance, clock = executor
    settings = manual_settings.read()
    payload, ack = start(instance, identifier)
    assert ack["status"] == "executed", ack
    run(instance, clock, payload, 7)
    row = instance.figures.current
    assert row["phase"] == "completed", row
    assert instance.gate.state == "DISARMED"
    assert instance.controller.stopped
    assert instance.controller.o_lx == instance.controller.o_az == 0
    assert not any(c[0] in {"action", "balance", "perform"} for c in instance.adapter.calls)
    assert all(75 <= c[1] <= 115 for c in instance.adapter.calls if c[0] == "height")
    assert all(abs(c[1]) <= 5 for c in instance.adapter.calls if c[0] == "roll")
    assert all(max(abs(c[1]), abs(c[2])) <= 0.25 for c in instance.adapter.calls if c[0] == "move")
    assert manual_settings.read() == settings
    assert row["physical_completion"] == "unverified"
    assert len(json.dumps(instance.snapshot())) < 65536


@pytest.mark.parametrize("identifier", list(NAMES))
@pytest.mark.parametrize("when", [0.04, 0.8, 1.6])
def test_stop_cancels_pose_and_wheel_steps_without_return_or_restart(executor, identifier, when):
    instance, clock = executor
    payload, _ = start(instance, identifier)
    run(instance, clock, payload, when)
    instance.apply(command(instance, "stop"))
    after = len(instance.adapter.calls)
    advance(instance, clock, 8)
    assert instance.figures.current["phase"] == "cancelled"
    assert instance.gate.state == "DISARMED"
    assert not any(
        c[0] in {"height", "roll"} or c[0] == "move" and (c[1] or c[2]) for c in instance.adapter.calls[after:]
    )


def test_contact_loss_is_terminal_and_status_reads_never_renew(executor):
    instance, clock = executor
    payload, _ = start(instance)
    advance(instance, clock, 0.52)
    assert instance.figures.current["reason"] == "figure_contact_lost"
    assert instance.gate.state == "DISARMED"
    assert keepalive(instance, payload)["status"] == "rejected"
    assert not instance.figures.active


def test_start_replay_cannot_restart_and_changed_request_conflicts(executor):
    instance, clock = executor
    payload, _ = start(instance)
    run(instance, clock, payload, 3)
    after = len(instance.adapter.calls)
    assert instance.apply(payload)["reason"] == "figure_replay"
    assert instance.apply({**payload, "figure_id": "snake"})["reason"] == "figure_request_conflict"
    assert len(instance.adapter.calls) == after


def test_manual_takeover_cancels_remaining_steps_without_disarming_new_goal(executor):
    instance, clock = executor
    payload, _ = start(instance)
    run(instance, clock, payload, 0.8)
    ack = instance.apply(intent(instance, "hold", "backward", panel_id="figures-panel"))
    assert ack["status"] == "accepted", ack
    assert instance.figures.current["phase"] == "cancelled"
    advance(instance, clock, 0.1)
    assert instance.gate.state == "ARMED"
    assert instance.controller.o_lx < 0


@pytest.mark.parametrize(
    "change",
    [
        {"operator_consent": False},
        {"figure_version": True},
        {"figure_id": "unknown"},
        {"panel_id": ""},
        {"source": "navigation"},
        {"execution_context": "agent"},
        {"settings_revision": True},
        {"figure_version": 2},
        {"steps": []},
        {"generation": "old"},
    ],
)
def test_invalid_start_never_arms_or_calls_hardware(executor, change):
    instance, _ = executor
    before = len(instance.adapter.calls)
    _, ack = start(instance, **change)
    assert ack["status"] == "rejected"
    assert instance.gate.state == "DISARMED"
    assert len(instance.adapter.calls) == before


def test_recipe_respects_saved_direction_caps_and_does_not_change_presets(executor):
    instance, _ = executor
    controls = manual_settings.read()
    controls["directions"]["forward"]["speed"] = 0.1
    assert max(s["vx"] for s in compile_recipe("forward_backward", controls)) == pytest.approx(0.03)
    rows = catalog({"height": True, "roll": False})["figures"]
    assert not next(r for r in rows if r["id"] == "sway")["available"]
    assert next(r for r in rows if r["id"] == "vertical")["available"]


def test_http_catalog_and_status_are_read_only_and_cancel_is_scoped(executor, monkeypatch):
    instance, _ = executor
    _, ack = start(instance)
    monkeypatch.setattr(figures_api, "read_status", lambda: {**instance.snapshot(), "stale": False})
    posts = []
    monkeypatch.setattr(figures_api, "submit_control", lambda body: (posts.append(body) or {"ok": True}, 200))
    with Flask(__name__).test_request_context():
        assert figures_api.catalog().get_json()["supported"]
        assert figures_api.status("figure-forward_backward").get_json()["run"]["phase"] == "preparing"
        assert not posts
        assert figures_api.cancel("foreign")[1] == 409
        figures_api.cancel("figure-forward_backward")
    assert posts == [{"action": "stop", "expected_generation": ack["generation"]}]


def test_late_keepalive_cannot_rescue_expired_contact_before_next_tick(executor):
    instance, clock = executor
    payload, _ = start(instance)
    clock.now += 0.51
    assert keepalive(instance, payload)["status"] == "rejected"
    assert instance.figures.current["reason"] == "figure_contact_lost"
    assert instance.gate.state == "DISARMED"


@pytest.mark.parametrize("failure", ["return_false", "exception"])
def test_posture_failure_is_terminal_without_later_steps(executor, failure):
    instance, clock = executor
    payload, _ = start(instance, "sway")

    def fail(_value):
        if failure == "exception":
            raise RuntimeError("fake disconnected")
        return False

    instance.adapter.set_roll = fail
    advance(instance, clock, 0.02)
    assert instance.figures.current["phase"] == "failed"
    assert instance.gate.state == "DISARMED"
    after = len(instance.adapter.calls)
    advance(instance, clock, 6)
    assert not any(c[0] in {"height", "roll"} for c in instance.adapter.calls[after:])


def test_several_runs_keep_status_bounded_and_mark_compacted_history(executor):
    instance, clock = executor
    for name in ["sway", "vertical", "circular_sway", "lift_rotate"]:
        payload, ack = start(instance, name)
        assert ack["status"] == "executed"
        run(instance, clock, payload, 7)
        assert instance.figures.current["phase"] == "completed"
        assert len(json.dumps(instance.snapshot()).encode()) < 65536
    assert len(instance.figures.snapshot()["history"]) == 3
    assert all(row["evidence_partial"] for row in instance.figures.snapshot()["history"])


def test_real_adapter_posture_uses_existing_owner_and_bounded_roll_only():
    from types import SimpleNamespace

    from apps.motion.main import _RealAdapter

    calls = []
    adapter = _RealAdapter.__new__(_RealAdapter)
    adapter._ada = SimpleNamespace(
        available_methods=lambda: ["rider_roll", "rider_height"],
        _allowed=lambda: True,
        _call=lambda name, value: calls.append((name, value)) or True,
    )
    assert adapter.figure_axes() == {"height": True, "roll": True}
    assert adapter.set_roll(3)
    assert calls == [("rider_roll", 3)]
    for value in [True, float("nan"), 5.1, -5.1]:
        assert adapter.set_roll(value) is False
    adapter._ada._allowed = lambda: False
    assert adapter.set_roll(0) is False
    assert calls == [("rider_roll", 3)]


def test_global_speed_limit_applies_before_any_sequence_is_armed():
    from apps.motion.figure_recipes import compile_recipe

    controls = manual_settings.read()
    controls["values"]["speed_limit"] = 0.02
    rows = compile_recipe("snake", controls)
    assert all(max(abs(row["vx"]), abs(row["yaw"])) <= 0.02 for row in rows)
