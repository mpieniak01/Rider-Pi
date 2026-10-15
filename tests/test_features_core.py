#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import time
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


def make_manager(runner: FakeRunner, publisher: NullPublisher, owner: str = "follow_me") -> FeatureManager:
    state_file = Path(tempfile.gettempdir()) / "feature_state_test.json"
    try:
        state_file.unlink()
    except FileNotFoundError:
        # File doesn't exist yet; nothing to clean up
        pass
    manager = FeatureManager(
        registry=DEFAULT_REGISTRY,
        runner=runner,
        status_fn=lambda unit: runner.state.get(unit, False),
        publisher=publisher,
        state_path=state_file,
        safety_status=lambda: {
            "ready": True,
            "can_move": True,
            "owner": owner,
            "generation": "fake-generation",
            "capabilities": {action: {"available": True, "stop_verified": True} for action in ("move", "turn")},
        },
        safety_stop=lambda owner: {"ok": True, "confirmed": True},
        dependency_check=lambda *args: [],
    )
    manager.producer_status = lambda unit: {
        "unit": unit,
        "accepted": True,
        "active": True,
        "generation": "fake-generation",
        "request_id": manager._service_intents().get(unit, {}).get("request_id"),
        "domains": ["asr", "tts", "chat"],
        "capabilities": {domain: {"ready": True} for domain in ("asr", "tts", "chat")},
    }
    original = manager.set_feature
    sequence = [0]

    def fake_intent(name, enabled):
        sequence[0] += 1
        return original(
            name,
            enabled,
            control={
                "source": "manual",
                "generation": "fake-generation",
                "seq": sequence[0],
                "ts": time.time(),
                "ttl_ms": 500,
                "request_id": f"fake-{sequence[0]}",
            },
        )

    manager.set_feature = fake_intent
    return manager


def test_enable_face_tracking_starts_preview_and_services() -> None:
    runner = FakeRunner()
    publisher = NullPublisher()
    mgr = make_manager(runner, publisher)

    result = mgr.set_feature("face_tracking", True)

    assert result["ok"] is True
    assert (
        runner.actions.index(("camera-capture@raw.service", "start"))
        < runner.actions.index(("frame-distributor.service", "start"))
        < runner.actions.index(("rider-followme.target", "start"))
    )
    assert ("rider-tracker.service", "start") in runner.actions
    assert ("rider-tracking-controller.service", "start") in runner.actions
    # Tracking mode event published
    assert publisher.sent[-1][0] == "tracking.mode:set"
    assert publisher.sent[-1][1]["mode"] == "face"


def test_dev_profile_does_not_start_or_stop_manual_jupyter() -> None:
    runner = FakeRunner()
    runner.state["jupyter.service"] = True
    mgr = make_manager(runner, NullPublisher())
    assert mgr.set_feature("s11_dev_mode", True)["ok"] is True
    assert mgr.set_feature("s11_dev_mode", False)["ok"] is True
    assert not any(unit == "jupyter.service" for unit, _ in runner.actions)
    assert runner.state["jupyter.service"] is True


def test_disable_face_tracking_stops_services_and_preview() -> None:
    runner = FakeRunner()
    runner.state["camera-capture@raw.service"] = True  # already running (autostart flag set on enable)
    runner.state["frame-distributor.service"] = True
    runner.state["rider-tracker.service"] = True
    runner.state["rider-tracking-controller.service"] = True
    runner.state["motion-executor.service"] = True
    publisher = NullPublisher()
    mgr = make_manager(runner, publisher)
    # Adopt an explicit task; camera/feed existed before the manager and stay external.
    assert mgr.set_feature("face_tracking", True)["ok"]
    runner.actions.clear()

    result = mgr.set_feature("face_tracking", False)

    assert result["ok"] is True
    assert runner.actions == [("rider-followme.target", "stop")]
    assert runner.state["camera-capture@raw.service"] and runner.state["frame-distributor.service"]
    # Tracking mode is reset to none
    assert publisher.sent[-1][1]["mode"] == "none"


def test_recon_unavailable_denied_before_preview_or_journal() -> None:
    runner = FakeRunner()
    publisher = NullPublisher()
    mgr = make_manager(runner, publisher, owner="navigation")

    enable = mgr.set_feature("recon", True)
    assert enable["ok"] is False and enable["error"] == "navigation_traversal_unverified"
    assert not runner.actions and not publisher.sent
    assert not mgr._intents and not mgr._pending and "s4_recon" not in mgr._requested


def test_describe_features_reports_metadata_and_status() -> None:
    runner = FakeRunner()
    publisher = NullPublisher()
    mgr = make_manager(runner, publisher)
    assert mgr.set_feature("face_tracking", True)["ok"]

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


def test_intent_rejection_reports_age_without_extending_ttl(monkeypatch):
    from services.core import features

    manager = make_manager(FakeRunner(), NullPublisher(), owner="navigation")
    monkeypatch.setattr(features.time, "time", lambda: 10.0)
    body = {
        "source": "navigation",
        "generation": "fake-generation",
        "seq": 1,
        "ts": 9.3,
        "ttl_ms": 500,
        "request_id": "expired",
    }
    result = manager._intent_permission(body)
    assert result["error"] == "stale_or_invalid_operator_intent"
    assert round(result["intent_diagnostic"]["age_ms"]) == 700
    assert result["intent_diagnostic"]["ttl_ms"] == 500
    assert result["intent_diagnostic"]["generation_matches"] is True
    assert not manager._intent_sequences
    assert manager._intent_permission({**body, "ts": 10.0}, consume=False) is None
    wrong = manager._intent_permission({**body, "ts": 10.0, "generation": "old"})
    assert wrong["intent_diagnostic"]["generation_matches"] is False
