from __future__ import annotations

from typing import TypedDict


class ServiceMeta(TypedDict):
    """Opis metadanych pojedynczego unitu systemd Rider-Pi."""

    id: str
    group: str
    label: str
    description: str
    edges_out: list[str]


SERVICE_META: dict[str, ServiceMeta] = {
    "rider-broker.service": {
        "id": "broker",
        "group": "core",
        "label": "Message broker (ZMQ)",
        "description": "Centralny bus komunikatów Rider-Pi.",
        "edges_out": [
            "vision",
            "tracker",
            "tracking-controller",
            "motion-bridge",
            "voice",
            "google-bridge",
            "mapper",
            "odometry",
        ],
    },
    "rider-api.service": {
        "id": "api",
        "group": "core",
        "label": "HTTP API",
        "description": "REST API oraz endpoints pomocnicze (Flask).",
        "edges_out": ["broker"],
    },
    "rider-vision.service": {
        "id": "vision",
        "group": "vision",
        "label": "Vision dispatcher",
        "description": "Zarządza pipeline'ami wizji i przekazuje dane do brokera.",
        "edges_out": ["tracker"],
    },
    "rider-motion-bridge.service": {
        "id": "motion-bridge",
        "group": "motion",
        "label": "Motion bridge (XGO)",
        "description": "Sterowanie robotem (XGO) oraz telemetria ruchu.",
        "edges_out": [],
    },
    "rider-boot-splash.service": {
        "id": "boot-splash",
        "group": "core",
        "label": "Boot splash",
        "description": "Przygotowanie środowiska i ekran startowy przy bootowaniu.",
        "edges_out": ["minimal-target"],
    },
    "rider-minimal.target": {
        "id": "minimal-target",
        "group": "core",
        "label": "Minimal target",
        "description": "Podstawowy zestaw usług Rider-Pi.",
        "edges_out": [],
    },
    "rider-edge-preview.service": {
        "id": "edge-preview",
        "group": "vision",
        "label": "Edge preview",
        "description": "Podgląd krawędzi (Canny) z kamery.",
        "edges_out": ["vision"],
    },
    "rider-obstacle.service": {
        "id": "obstacle",
        "group": "vision",
        "label": "Obstacle detector",
        "description": "Wykrywanie przeszkód i publikacja na brokerze.",
        "edges_out": ["broker"],
    },
    "rider-cam-preview.service": {
        "id": "cam-preview",
        "group": "vision",
        "label": "Camera preview",
        "description": "Podgląd kamery oraz wysyłka klatek do wizji.",
        "edges_out": ["vision"],
    },
    "rider-ssd-preview.service": {
        "id": "ssd-preview",
        "group": "vision",
        "label": "SSD preview",
        "description": "Podgląd kamery z detekcją SSD.",
        "edges_out": ["vision"],
    },
    "jupyter.service": {
        "id": "jupyter",
        "group": "dev",
        "label": "Jupyter Lab",
        "description": "Środowisko deweloperskie Jupyter Lab.",
        "edges_out": [],
    },
    "rider-dev.target": {
        "id": "dev-target",
        "group": "core",
        "label": "Dev target",
        "description": "Cel systemd dla usług developerskich (np. Jupyter).",
        "edges_out": ["jupyter"],
    },
    "rider-web-bridge.service": {
        "id": "web-bridge",
        "group": "core",
        "label": "Web bridge",
        "description": "Mostek webowy (HTTP↔motion/vision).",
        "edges_out": ["api"],
    },
    "rider-voice.service": {
        "id": "voice",
        "group": "voice",
        "label": "Voice core",
        "description": "Silnik głosowy (rozpoznawanie i komendy).",
        "edges_out": ["api"],
    },
    "rider-voice-web.service": {
        "id": "voice-web",
        "group": "voice",
        "label": "Voice web",
        "description": "Interfejs webowy dla modułu głosowego.",
        "edges_out": ["voice"],
    },
    "rider-choreographer.service": {
        "id": "choreographer",
        "group": "motion",
        "label": "Choreographer",
        "description": "Koordynuje animacje i gesty robota.",
        "edges_out": ["motion-bridge"],
    },
    "wifi-unblock.service": {
        "id": "wifi-unblock",
        "group": "core",
        "label": "Wi-Fi unblock",
        "description": "Odblokowanie modułu Wi-Fi przy starcie.",
        "edges_out": [],
    },
    "rider-google-bridge.service": {
        "id": "google-bridge",
        "group": "cloud",
        "label": "Google bridge",
        "description": "Integracja z usługami Google (Home).",
        "edges_out": ["api", "broker"],
    },
    "rider-post-splash.service": {
        "id": "post-splash",
        "group": "core",
        "label": "Post splash",
        "description": "Wyświetlanie informacji po ekranie startowym.",
        "edges_out": ["web-bridge"],
    },
    "rider-mapper.service": {
        "id": "mapper",
        "group": "motion",
        "label": "Mapper",
        "description": "SLAM/rekonesans — budowa mapy otoczenia.",
        "edges_out": ["api"],
    },
    "rider-odometry.service": {
        "id": "odometry",
        "group": "motion",
        "label": "Odometry",
        "description": "Śledzenie pozycji robota na podstawie IMU/ENC.",
        "edges_out": ["mapper"],
    },
    "rider-tracker.service": {
        "id": "tracker",
        "group": "vision",
        "label": "Tracker",
        "description": "Śledzenie obiektów (Follow Me).",
        "edges_out": ["tracking-controller"],
    },
    "rider-tracking-controller.service": {
        "id": "tracking-controller",
        "group": "motion",
        "label": "Tracking controller",
        "description": "Sterowanie ruchem na podstawie śledzenia.",
        "edges_out": ["motion-bridge"],
    },
    "rider-navigator.service": {
        "id": "navigator",
        "group": "motion",
        "label": "Navigator",
        "description": "Autonomiczny rekonesans i sterowanie ruchem.",
        "edges_out": ["motion-bridge"],
    },
    "rider-vision-offload.service": {
        "id": "vision-offload",
        "group": "vision",
        "label": "Vision offload",
        "description": "Dispatcher wizji publikujący strumień do PC.",
        "edges_out": ["broker"],
    },
}


SERVICE_IDS_BY_UNIT: dict[str, str] = {unit: meta["id"] for unit, meta in SERVICE_META.items()}

UNIT_BY_ID: dict[str, str] = {meta["id"]: unit for unit, meta in SERVICE_META.items()}


__all__ = ["SERVICE_META", "SERVICE_IDS_BY_UNIT", "UNIT_BY_ID", "ServiceMeta"]
