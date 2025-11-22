#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from common import bus, systemd_ctrl


@dataclass(frozen=True)
class FeatureDefinition:
    """Opis funkcji robota: jakie usługi uruchamia i czy wymaga podglądu CAM."""

    name: str
    services: Sequence[str]
    ensure_cam: bool = False
    tracking_mode: str | None = None  # tylko dla funkcji śledzenia


class NullPublisher:
    """Prosty publisher do testów (nie wymaga ZMQ)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    def publish(self, topic: str, payload: dict, add_ts: bool = False) -> None:
        self.sent.append((topic, dict(payload)))


DEFAULT_REGISTRY: dict[str, FeatureDefinition] = {
    "face_tracking": FeatureDefinition(
        name="face_tracking",
        services=("rider-tracker.service", "rider-tracking-controller.service"),
        ensure_cam=True,
        tracking_mode="face",
    ),
    "hand_tracking": FeatureDefinition(
        name="hand_tracking",
        services=("rider-tracker.service", "rider-tracking-controller.service"),
        ensure_cam=True,
        tracking_mode="hand",
    ),
    "recon": FeatureDefinition(
        name="recon",
        services=(
            "rider-vision.service",
            "rider-obstacle.service",
            "rider-motion-bridge.service",
            "rider-odometry.service",
            "rider-mapper.service",
            "rider-navigator.service",
        ),
        ensure_cam=False,
        tracking_mode=None,
    ),
}


def _as_dict(result: object) -> dict:
    """Ujednolicenie ActionResult → dict."""
    if hasattr(result, "as_dict"):
        return result.as_dict()  # type: ignore[no-any-return]
    if isinstance(result, dict):
        return result
    raise TypeError(f"Unsupported result type: {type(result)!r}")


class FeatureManager:
    """Pojedyncze źródło prawdy dla funkcji robota (start/stop)."""

    PREVIEW_UNIT = "rider-cam-preview.service"

    def __init__(
        self,
        registry: dict[str, FeatureDefinition] | None = None,
        runner: Callable[[str, str], object] | None = None,
        status_fn: Callable[[str], bool] | None = None,
        publisher: object | None = None,
    ) -> None:
        self.registry = registry or DEFAULT_REGISTRY
        self.runner = runner or systemd_ctrl.run_unit_action
        self.status_fn = status_fn or systemd_ctrl.is_active
        self.publisher = publisher or bus.BusPub()
        self._preview_autostart = False

    def _publish_tracking_mode(self, mode: str) -> None:
        """Publikuj zmianę trybu śledzenia (Follow Me)."""
        self.publisher.publish(bus.TOPIC_TRACKING_MODE_SET, {"mode": mode}, add_ts=True)

    def _ensure_preview(self, feature: FeatureDefinition) -> list[dict]:
        steps: list[dict] = []
        if not feature.ensure_cam:
            return steps
        if self.status_fn(self.PREVIEW_UNIT):
            return steps
        result = self.runner(self.PREVIEW_UNIT, "start")
        steps.append(_as_dict(result))
        if steps[-1].get("ok"):
            self._preview_autostart = True
        return steps

    def _stop_preview_if_auto(self) -> list[dict]:
        steps: list[dict] = []
        if not self._preview_autostart:
            return steps
        result = self.runner(self.PREVIEW_UNIT, "stop")
        steps.append(_as_dict(result))
        if steps[-1].get("ok"):
            self._preview_autostart = False
        return steps

    def _run_services(self, services: Iterable[str], action: str) -> list[dict]:
        steps: list[dict] = []
        for unit in services:
            res = self.runner(unit, action)
            steps.append(_as_dict(res))
        return steps

    def set_feature(self, name: str, enabled: bool) -> dict:
        """
        Włącz/wyłącz funkcję.
        Zwraca słownik: {"ok": bool, "steps": [...], "events": [...]}.
        """
        if name not in self.registry:
            raise ValueError(f"unknown feature: {name}")
        feature = self.registry[name]
        steps: list[dict] = []
        events: list[dict] = []

        if enabled:
            steps.extend(self._ensure_preview(feature))
            steps.extend(self._run_services(feature.services, "start"))
            if feature.tracking_mode:
                self._publish_tracking_mode(feature.tracking_mode)
                events.append({"topic": bus.TOPIC_TRACKING_MODE_SET, "mode": feature.tracking_mode})
        else:
            if feature.tracking_mode:
                self._publish_tracking_mode("none")
                events.append({"topic": bus.TOPIC_TRACKING_MODE_SET, "mode": "none"})
            steps.extend(self._run_services(reversed(feature.services), "stop"))
            steps.extend(self._stop_preview_if_auto())

        ok = all(s.get("ok") for s in steps) if steps else True
        return {"ok": ok, "steps": steps, "events": events}


__all__ = ["FeatureDefinition", "FeatureManager", "DEFAULT_REGISTRY", "NullPublisher"]
