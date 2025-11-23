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
            "motion-executor",
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
    "camera-capture@raw.service": {
        "id": "camera-capture-raw",
        "group": "vision",
        "label": "Camera capture (raw)",
        "description": "Podstawowy podgląd kamery + publikacja klatek.",
        "edges_out": ["vision"],
    },
    "camera-capture@edge.service": {
        "id": "camera-capture-edge",
        "group": "vision",
        "label": "Camera capture (edge)",
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
    "camera-capture@ssd.service": {
        "id": "camera-capture-ssd",
        "group": "vision",
        "label": "Camera capture (SSD)",
        "description": "Podgląd kamery z aktywną detekcją SSD.",
        "edges_out": ["vision"],
    },
    "frame-distributor.service": {
        "id": "frame-distributor",
        "group": "vision",
        "label": "Frame distributor",
        "description": "Publikuje wspólny strumień klatek dla modułów wizji.",
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
        "edges_out": ["motion-executor"],
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
    "lcd-renderer.service": {
        "id": "lcd-renderer",
        "group": "core",
        "label": "LCD renderer",
        "description": "Renderuje aktywne scenariusze na LCD na podstawie App Logic.",
        "edges_out": [],
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
        "edges_out": ["motion-executor"],
    },
    "rider-navigator.service": {
        "id": "navigator",
        "group": "motion",
        "label": "Navigator",
        "description": "Autonomiczny rekonesans i sterowanie ruchem.",
        "edges_out": ["motion-executor"],
    },
    "rider-vision-offload.service": {
        "id": "vision-offload",
        "group": "vision",
        "label": "Vision offload",
        "description": "Dispatcher wizji publikujący strumień do PC.",
        "edges_out": ["broker"],
    },
    "sensor-reader.service": {
        "id": "sensor-reader",
        "group": "motion",
        "label": "Sensor reader",
        "description": "Czyta IMU/baterię z XGO i publikuje imu.data/devices.xgo.",
        "edges_out": ["api"],
    },
    "motion-executor.service": {
        "id": "motion-executor",
        "group": "motion",
        "label": "Motion executor",
        "description": "Wykonuje cmd.move / tracking.pose na XGO z deadmanem.",
        "edges_out": ["api"],
    },
    "rider-voice.target": {
        "id": "voice-target",
        "group": "voice",
        "label": "Voice target",
        "description": "Scenariusz głosowy (S5) – audio input/output + integracje.",
        "edges_out": ["voice"],
    },
    "rider-mapbuild.target": {
        "id": "mapbuild-target",
        "group": "motion",
        "label": "Map build target",
        "description": "Scenariusz S8 – capture + obstacle + odometry + mapper.",
        "edges_out": ["mapper"],
    },
    "rider-navigate.target": {
        "id": "navigate-target",
        "group": "motion",
        "label": "Navigate target",
        "description": "Scenariusz S9 – nawigacja A→B z mapy.",
        "edges_out": ["navigator"],
    },
    "audio-input.target": {
        "id": "audio-input",
        "group": "voice",
        "label": "Audio input",
        "description": "Logika mikrofonu/ASR (wants rider-voice.service).",
        "edges_out": ["voice"],
    },
    "audio-output.target": {
        "id": "audio-output",
        "group": "voice",
        "label": "Audio output",
        "description": "Logika wyjścia audio/TTS (wants rider-voice-web.service).",
        "edges_out": ["voice"],
    },
}


SERVICE_IDS_BY_UNIT: dict[str, str] = {unit: meta["id"] for unit, meta in SERVICE_META.items()}

UNIT_BY_ID: dict[str, str] = {meta["id"]: unit for unit, meta in SERVICE_META.items()}


__all__ = ["SERVICE_META", "SERVICE_IDS_BY_UNIT", "UNIT_BY_ID", "ServiceMeta"]
