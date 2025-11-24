#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from common import bus, systemd_ctrl


@dataclass(frozen=True)
class FeatureDefinition:
    """Opis scenariusza/feature'u oraz usług systemd, które go realizują."""

    name: str
    services: Sequence[str]
    ensure_cam: bool = False
    tracking_mode: str | None = None  # tylko dla funkcji śledzenia
    scenario: str | None = None  # np. "S3"
    title: str | None = None  # nazwa scenariusza z dokumentacji
    description: str | None = None  # skrótowy opis celu biznesowego


class NullPublisher:
    """Prosty publisher do testów (nie wymaga ZMQ)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    def publish(self, topic: str, payload: dict, add_ts: bool = False) -> None:
        self.sent.append((topic, dict(payload)))


DEFAULT_REGISTRY: dict[str, FeatureDefinition] = {
    "s0_core": FeatureDefinition(
        name="s0_core",
        scenario="S0",
        title='Tryb bazowy "read only"',
        description="Uruchamia podstawowe usługi UI/API/bus bez aktywnego sterowania.",
        services=("rider-core.target",),
    ),
    "s1_manual": FeatureDefinition(
        name="s1_manual",
        scenario="S1",
        title="Sterowanie manualne",
        description="Świadome włączenie przekazywania komend ruchu przez motion-executor.",
        services=(
            "rider-core.target",
            "motion-executor.service",
            "sensor-reader.service",
        ),
    ),
    "s2_camera_preview": FeatureDefinition(
        name="s2_camera_preview",
        scenario="S2",
        title="Podgląd kamery",
        description="Udostępnia podstawowy feed z kamery do UI i modułów ML.",
        services=("camera-capture@raw.service", "frame-distributor.service"),
        ensure_cam=True,
    ),
    "s3_follow_me_face": FeatureDefinition(
        name="s3_follow_me_face",
        scenario="S3",
        title="Follow Me – twarz",
        description="Śledzenie osoby i przekazywanie komend do XGO (tryb twarz).",
        services=("rider-followme.target",),
        ensure_cam=True,
        tracking_mode="face",
    ),
    "s3_follow_me_hand": FeatureDefinition(
        name="s3_follow_me_hand",
        scenario="S3",
        title="Follow Me – dłoń",
        description="Śledzenie dłoni wraz z kontrolą ruchu.",
        services=("rider-followme.target",),
        ensure_cam=True,
        tracking_mode="hand",
    ),
    "s4_recon": FeatureDefinition(
        name="s4_recon",
        scenario="S4",
        title="Rekonesans / Patrol",
        description="Autonomiczny patrol z mapowaniem i omijaniem przeszkód.",
        services=("rider-recon.target",),
        ensure_cam=True,
    ),
    "s5_voice": FeatureDefinition(
        name="s5_voice",
        scenario="S5",
        title="Komunikacja głosowa",
        description="Asystent głosowy: ASR/TTS + warstwa web.",
        services=("rider-voice.target",),
    ),
    "s6_tracker_module": FeatureDefinition(
        name="s6_tracker_module",
        scenario="S6",
        title="Moduł śledzenia obiektów",
        description="Samodzielny tracker (wizja) bez sterowania ruchem.",
        services=("rider-tracker.target",),
        ensure_cam=True,
    ),
    "s7_obstacle_module": FeatureDefinition(
        name="s7_obstacle_module",
        scenario="S7",
        title="Moduł wykrywania przeszkód",
        description="Analiza obrazu i alerty przeszkód w tle.",
        services=("rider-obstacle.target",),
        ensure_cam=True,
    ),
    "s8_mapping": FeatureDefinition(
        name="s8_mapping",
        scenario="S8",
        title="Rekonesans mapujący",
        description="Budowa map SLAM na potrzeby przyszłej nawigacji.",
        services=("rider-mapbuild.target",),
        ensure_cam=True,
    ),
    "s9_navigation": FeatureDefinition(
        name="s9_navigation",
        scenario="S9",
        title="Nawigacja po mapie",
        description="Wykonywanie tras A→B po wcześniej zapisanej mapie.",
        services=("rider-navigate.target",),
    ),
    "s10_ai_providers": FeatureDefinition(
        name="s10_ai_providers",
        scenario="S10",
        title="Wybór providerów AI",
        description="Przełączanie między lokalnymi/chmurowymi providerami głosu i wizji.",
        services=("rider-ai-provider.target",),
    ),
    "s11_dev_mode": FeatureDefinition(
        name="s11_dev_mode",
        scenario="S11",
        title="Tryb deweloperski",
        description="Profile testowe i narzędzia developerskie (Jupyter, legacy preview).",
        services=(
            "rider-dev.target",
            "jupyter.service",
            "rider-face.service",
            "camera-capture@edge.service",
            "camera-capture@ssd.service",
        ),
    ),
}

DEFAULT_ALIASES: dict[str, str] = {
    "face_tracking": "s3_follow_me_face",
    "hand_tracking": "s3_follow_me_hand",
    "recon": "s4_recon",
    "follow_me": "s3_follow_me_face",
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

    PREVIEW_UNIT = "camera-capture@raw.service"
    FRAME_FEED_UNIT = "frame-distributor.service"

    def __init__(
        self,
        registry: dict[str, FeatureDefinition] | None = None,
        runner: Callable[[str, str], object] | None = None,
        status_fn: Callable[[str], bool] | None = None,
        publisher: object | None = None,
        aliases: dict[str, str] | None = None,
        state_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.registry = registry or DEFAULT_REGISTRY
        self.runner = runner or systemd_ctrl.run_unit_action
        self.status_fn = status_fn or systemd_ctrl.is_active
        self.publisher = publisher or bus.BusPub()
        self.aliases = aliases or DEFAULT_ALIASES
        self._preview_autostart = False
        self._framefeed_autostart = False
        self._active_features: set[str] = set()
        self._state_path = Path(state_path or os.getenv("FEATURE_STATE_PATH", "/run/rider/feature_state.json"))
        self._state_cache: dict[str, object] = {"ts": 0.0, "active": [], "features": []}
        self._initialize_active_features()

    def _resolve_name(self, requested: str) -> str:
        """Zwraca kanoniczną nazwę feature'u uwzględniając aliasy."""
        if requested in self.registry:
            return requested
        target = self.aliases.get(requested)
        if target and target in self.registry:
            return target
        raise ValueError(f"unknown feature: {requested}")

    def _publish_tracking_mode(self, mode: str) -> None:
        """Publikuj zmianę trybu śledzenia (Follow Me)."""
        self.publisher.publish(bus.TOPIC_TRACKING_MODE_SET, {"mode": mode}, add_ts=True)

    def _ensure_preview(self, feature: FeatureDefinition) -> list[dict]:
        steps: list[dict] = []
        if not feature.ensure_cam:
            return steps
        if not self.status_fn(self.PREVIEW_UNIT):
            result = self.runner(self.PREVIEW_UNIT, "start")
            steps.append(_as_dict(result))
            if steps[-1].get("ok"):
                self._preview_autostart = True
        if not self.status_fn(self.FRAME_FEED_UNIT):
            result = self.runner(self.FRAME_FEED_UNIT, "start")
            steps.append(_as_dict(result))
            if steps[-1].get("ok"):
                self._framefeed_autostart = True
        return steps

    def _stop_preview_if_auto(self) -> list[dict]:
        steps: list[dict] = []
        if self._framefeed_autostart:
            result = self.runner(self.FRAME_FEED_UNIT, "stop")
            steps.append(_as_dict(result))
            if steps[-1].get("ok"):
                self._framefeed_autostart = False
        if self._preview_autostart:
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

    def _initialize_active_features(self) -> None:
        for name, feature in self.registry.items():
            if all(self.status_fn(unit) for unit in feature.services):
                self._active_features.add(name)
        self._persist_state()

    def _persist_state(self) -> None:
        data = {
            "ts": time.time(),
            "active": sorted(self._active_features),
            "features": self.describe_features(),
        }
        self._state_cache = data
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._state_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            tmp_path.replace(self._state_path)
        except Exception as exc:
            # State persistence is best-effort; failures don't block operations
            print(f"[features] WARNING: State save failed: {exc}", file=sys.stderr, flush=True)

    def state_snapshot(self) -> dict:
        return json.loads(json.dumps(self._state_cache, ensure_ascii=False))

    def describe_features(self) -> list[dict]:
        """Zwraca listę scenariuszy wraz z metadanymi i statusem usług."""
        alias_index: dict[str, list[str]] = {}
        for alias, canonical in self.aliases.items():
            alias_index.setdefault(canonical, []).append(alias)

        rows: list[dict] = []
        for name, feature in self.registry.items():
            services = [{"unit": unit, "active": bool(self.status_fn(unit))} for unit in feature.services]
            is_active = bool(services and all(s["active"] for s in services))
            rows.append(
                {
                    "name": name,
                    "scenario": feature.scenario,
                    "title": feature.title,
                    "description": feature.description,
                    "ensure_cam": feature.ensure_cam,
                    "tracking_mode": feature.tracking_mode,
                    "aliases": sorted(alias_index.get(name, [])),
                    "services": services,
                    "active": is_active,
                }
            )

        rows.sort(key=lambda row: (row["scenario"] or row["name"]))
        return rows

    def set_feature(self, name: str, enabled: bool) -> dict:
        """
        Włącz/wyłącz funkcję.
        Zwraca słownik: {"ok": bool, "steps": [...], "events": [...]}.
        """
        canonical = self._resolve_name(name)
        feature = self.registry[canonical]
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
        if ok:
            if enabled:
                self._active_features.add(canonical)
            else:
                self._active_features.discard(canonical)
        self._persist_state()
        return {"ok": ok, "steps": steps, "events": events}


__all__ = ["FeatureDefinition", "FeatureManager", "DEFAULT_REGISTRY", "DEFAULT_ALIASES", "NullPublisher"]
