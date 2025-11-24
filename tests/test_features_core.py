#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

from apps.app_logic_core import DEFAULT_REGISTRY, FeatureManager, NullPublisher
from common import systemd_ctrl


class FakeRunner:
    """Symuluje systemd run_unit_action – zapisuje akcje i stan jednostek."""

    def __init__(self) -> None:
        self.actions: list[tuple[str, str]] = []
        self.state: dict[str, bool] = {}

    def __call__(self, unit: str, action: str) -> systemd_ctrl.ActionResult:
        self.actions.append((unit, action))
        if action == "start":
            self.state[unit] = True
        elif action == "stop":
            self.state[unit] = False
        return systemd_ctrl.ActionResult(
            unit=unit,
            action=action,
            method="fake",
            ok=True,
            rc=0,
            stdout="",
            stderr="",
        )


def make_manager(runner: FakeRunner, publisher: NullPublisher) -> FeatureManager:
    state_file = Path(tempfile.gettempdir()) / "feature_state_test.json"
    try:
        state_file.unlink()
    except FileNotFoundError:
        # File doesn't exist yet; nothing to clean up
        pass
    return FeatureManager(
        registry=DEFAULT_REGISTRY,
        runner=runner,
        status_fn=lambda unit: runner.state.get(unit, False),
        publisher=publisher,
        state_path=state_file,
    )


def test_enable_face_tracking_starts_preview_and_services() -> None:
    runner = FakeRunner()
    publisher = NullPublisher()
    mgr = make_manager(runner, publisher)

    result = mgr.set_feature("face_tracking", True)

    assert result["ok"] is True
    # Preview starts first, then feature services
    assert runner.actions[:3] == [
        ("camera-capture@raw.service", "start"),
        ("frame-distributor.service", "start"),
        ("rider-followme.target", "start"),
    ]
    # Tracking mode event published
    assert publisher.sent[-1][0] == "tracking.mode:set"
    assert publisher.sent[-1][1]["mode"] == "face"


def test_disable_face_tracking_stops_services_and_preview() -> None:
    runner = FakeRunner()
    runner.state["camera-capture@raw.service"] = True  # already running (autostart flag set on enable)
    runner.state["frame-distributor.service"] = True
    runner.state["rider-tracker.service"] = True
    runner.state["rider-tracking-controller.service"] = True
    runner.state["motion-executor.service"] = True
    publisher = NullPublisher()
    mgr = make_manager(runner, publisher)
    # symulacja wcześniejszego auto-startu podglądu
    mgr._preview_autostart = True
    mgr._framefeed_autostart = True

    result = mgr.set_feature("face_tracking", False)

    assert result["ok"] is True
    # Stop services in reverse order, then preview
    assert runner.actions == [
        ("rider-followme.target", "stop"),
        ("frame-distributor.service", "stop"),
        ("camera-capture@raw.service", "stop"),
    ]
    # Tracking mode is reset to none
    assert publisher.sent[-1][1]["mode"] == "none"


def test_enable_disable_recon_sequence_and_no_preview() -> None:
    runner = FakeRunner()
    publisher = NullPublisher()
    mgr = make_manager(runner, publisher)

    enable = mgr.set_feature("recon", True)
    assert enable["ok"] is True
    assert ("camera-capture@raw.service", "start") in runner.actions
    assert ("frame-distributor.service", "start") in runner.actions
    assert ("rider-recon.target", "start") in runner.actions
    assert publisher.sent == []  # brak eventów dla recon

    runner.actions.clear()
    disable = mgr.set_feature("recon", False)
    assert disable["ok"] is True
    assert ("rider-recon.target", "stop") in runner.actions
    assert ("frame-distributor.service", "stop") in runner.actions
    assert ("camera-capture@raw.service", "stop") in runner.actions


def test_describe_features_reports_metadata_and_status() -> None:
    runner = FakeRunner()
    publisher = NullPublisher()
    mgr = make_manager(runner, publisher)
    runner.state["rider-followme.target"] = True
    runner.state["camera-capture@raw.service"] = True
    runner.state["frame-distributor.service"] = True

    data = mgr.describe_features()
    s3 = next(item for item in data if item["name"] == "s3_follow_me_face")

    assert s3["scenario"] == "S3"
    assert "face_tracking" in s3["aliases"]
    assert s3["active"] is True
    assert {"rider-followme.target"} <= {svc["unit"] for svc in s3["services"]}


def test_state_snapshot_tracks_active_features() -> None:
    runner = FakeRunner()
    publisher = NullPublisher()
    mgr = make_manager(runner, publisher)

    mgr.set_feature("face_tracking", True)
    state = mgr.state_snapshot()
    assert "s3_follow_me_face" in state["active"]

    mgr.set_feature("face_tracking", False)
    state2 = mgr.state_snapshot()
    assert "s3_follow_me_face" not in state2["active"]
