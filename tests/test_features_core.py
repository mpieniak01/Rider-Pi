#!/usr/bin/env python3
from __future__ import annotations

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
    return FeatureManager(
        registry=DEFAULT_REGISTRY,
        runner=runner,
        status_fn=lambda unit: runner.state.get(unit, False),
        publisher=publisher,
    )


def test_enable_face_tracking_starts_preview_and_services() -> None:
    runner = FakeRunner()
    publisher = NullPublisher()
    mgr = make_manager(runner, publisher)

    result = mgr.set_feature("face_tracking", True)

    assert result["ok"] is True
    # Preview starts first, then feature services
    assert runner.actions[:3] == [
        ("rider-cam-preview.service", "start"),
        ("rider-tracker.service", "start"),
        ("rider-tracking-controller.service", "start"),
    ]
    # Tracking mode event published
    assert publisher.sent[-1][0] == "tracking.mode:set"
    assert publisher.sent[-1][1]["mode"] == "face"


def test_disable_face_tracking_stops_services_and_preview() -> None:
    runner = FakeRunner()
    runner.state["rider-cam-preview.service"] = True  # already running (autostart flag set on enable)
    runner.state["rider-tracker.service"] = True
    runner.state["rider-tracking-controller.service"] = True
    publisher = NullPublisher()
    mgr = make_manager(runner, publisher)
    # symulacja wcześniejszego auto-startu podglądu
    mgr._preview_autostart = True

    result = mgr.set_feature("face_tracking", False)

    assert result["ok"] is True
    # Stop services in reverse order, then preview
    assert runner.actions == [
        ("rider-tracking-controller.service", "stop"),
        ("rider-tracker.service", "stop"),
        ("rider-cam-preview.service", "stop"),
    ]
    # Tracking mode is reset to none
    assert publisher.sent[-1][1]["mode"] == "none"


def test_enable_disable_recon_sequence_and_no_preview() -> None:
    runner = FakeRunner()
    publisher = NullPublisher()
    mgr = make_manager(runner, publisher)

    enable = mgr.set_feature("recon", True)
    assert enable["ok"] is True
    assert runner.actions[:6] == [
        ("rider-vision.service", "start"),
        ("rider-obstacle.service", "start"),
        ("rider-motion-bridge.service", "start"),
        ("rider-odometry.service", "start"),
        ("rider-mapper.service", "start"),
        ("rider-navigator.service", "start"),
    ]
    assert publisher.sent == []  # brak eventów dla recon

    runner.actions.clear()
    disable = mgr.set_feature("recon", False)
    assert disable["ok"] is True
    assert runner.actions == [
        ("rider-navigator.service", "stop"),
        ("rider-mapper.service", "stop"),
        ("rider-odometry.service", "stop"),
        ("rider-motion-bridge.service", "stop"),
        ("rider-obstacle.service", "stop"),
        ("rider-vision.service", "stop"),
    ]
