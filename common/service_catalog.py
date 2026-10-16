"""Versioned Pi catalog shared by HTTP, orchestration and privileged tools.

Importing this module performs no systemd, BUS or hardware I/O.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from typing import Sequence

from .compute_catalog import EN as COMPUTE_EN, compute_availability, compute_features

CONTRACT_VERSION = 2
HOST = "pi"
BOOT_UNITS = ("rider-minimal.target", "rider-boot-splash.service", "lcd-renderer.service", "wifi-unblock.service")


@dataclass(frozen=True)
class FeatureDefinition:
    name: str
    services: Sequence[str]
    ensure_cam: bool = False
    tracking_mode: str | None = None
    scenario: str | None = None
    title: str | None = None
    description: str | None = None
    members: Sequence[str] = ()
    resources: Sequence[str] = ()
    can_move: bool = False
    control_owner: str | None = None
    option_kind: str | None = None
    title_en: str | None = None
    description_en: str | None = None
    compute_tasks: Sequence[str] = ()


_EN = {
    **COMPUTE_EN,
    "s0_core": ("Base / observation", "API and telemetry, without actuator permission."),
    "s1_manual": ("Manual control", "Requires separate operator arming."),
    "s2_camera_preview": ("Camera preview", "Passive camera feed."),
    "s3_follow_me_face": ("Follow Me — face", "Tracking with actuators."),
    "s3_follow_me_hand": ("Follow Me — hand", "Tracking with actuators."),
    "s4_recon": ("Reconnaissance", "Navigation and mapping with actuators."),
    "s5_voice": ("Voice", "Only the selected audio domain."),
    "s6_tracker_module": ("Passive tracker", "Observation without a motion controller."),
    "s7_obstacle_module": ("Obstacles", "Local vision or PC offload."),
    "s8_mapping": ("Passive mapping", "Build a map from observations without starting navigation."),
    "s9_navigation": (
        "Passive navigation",
        "Observe existing plans; physical traversal and DISARMED planning requests are unavailable.",
    ),
    "s10_ai_providers": ("AI domain", "Start only the selected domain."),
    "s11_dev_mode": ("Developer tool", "One tool; Jupyter is manual."),
}


BASE_UNITS = (
    "rider-broker.service",
    "rider-api.service",
    "motion-executor.service",
    "sensor-reader.service",
    "rider-web-bridge.service",
)
CAMERA_UNITS = ("camera-capture@raw.service", "frame-distributor.service")
MAP_UNITS = (
    *CAMERA_UNITS,
    "rider-vision.service",
    "rider-obstacle.service",
    "rider-odometry.service",
    "rider-mapper.service",
)


def _feature(
    name: str,
    scenario: str,
    title: str,
    description: str,
    target: str,
    members: Sequence[str] = (),
    resources: Sequence[str] = (),
    **kwargs,
) -> FeatureDefinition:
    return FeatureDefinition(
        name,
        (target,),
        scenario=scenario,
        title=title,
        description=description,
        title_en=_EN[name][0],
        description_en=_EN[name][1],
        members=members,
        resources=resources,
        ensure_cam="camera" in resources,
        **kwargs,
    )


DEFAULT_REGISTRY = {
    **compute_features(_feature, CAMERA_UNITS),
    "s0_core": _feature(
        "s0_core", "S0", "Baza / odczyt", "API i telemetria, bez zgody na napędy.", "rider-core.target", BASE_UNITS
    ),
    "s1_manual": _feature(
        "s1_manual",
        "S1",
        "Sterowanie ręczne",
        "Wymaga osobnego uzbrojenia operatora.",
        "rider-core.target",
        BASE_UNITS,
        ("control",),
        can_move=True,
        control_owner="manual",
    ),
    "s2_camera_preview": _feature(
        "s2_camera_preview",
        "S2",
        "Podgląd kamery",
        "Pasywny obraz z kamery.",
        "rider-core.target",
        CAMERA_UNITS,
        ("camera", "frame_feed"),
    ),
    "s3_follow_me_face": _feature(
        "s3_follow_me_face",
        "S3",
        "Follow Me — twarz",
        "Śledzenie z napędami.",
        "rider-followme.target",
        (*CAMERA_UNITS, "rider-tracker.service", "rider-tracking-controller.service"),
        ("camera", "frame_feed", "control"),
        tracking_mode="face",
        can_move=True,
        control_owner="follow_me",
    ),
    "s3_follow_me_hand": _feature(
        "s3_follow_me_hand",
        "S3",
        "Follow Me — dłoń",
        "Śledzenie z napędami.",
        "rider-followme.target",
        (*CAMERA_UNITS, "rider-tracker.service", "rider-tracking-controller.service"),
        ("camera", "frame_feed", "control"),
        tracking_mode="hand",
        can_move=True,
        control_owner="follow_me",
    ),
    "s4_recon": _feature(
        "s4_recon",
        "S4",
        "Rekonesans",
        "Nawigacja i mapowanie z napędami.",
        "rider-recon.target",
        (*MAP_UNITS, "rider-navigator.service"),
        ("camera", "frame_feed", "control"),
        can_move=True,
        control_owner="navigation",
    ),
    "s5_voice": _feature(
        "s5_voice",
        "S5",
        "Głos",
        "Wyłącznie wybrana domena audio.",
        "rider-voice.target",
        resources=("mic", "speaker"),
        option_kind="voice",
    ),
    "s6_tracker_module": _feature(
        "s6_tracker_module",
        "S6",
        "Tracker pasywny",
        "Obserwacja bez kontrolera ruchu.",
        "rider-tracker.target",
        (*CAMERA_UNITS, "rider-tracker.service"),
        ("camera", "frame_feed"),
        option_kind="tracking",
    ),
    "s7_obstacle_module": _feature(
        "s7_obstacle_module",
        "S7",
        "Przeszkody",
        "Wizja lokalna albo offload.",
        "rider-obstacle.target",
        resources=("camera", "frame_feed"),
        option_kind="vision",
    ),
    "s8_mapping": _feature(
        "s8_mapping",
        "S8",
        "Mapa pasywna",
        "Budowa mapy z danych; nie uruchamia nawigatora.",
        "rider-mapbuild.target",
        MAP_UNITS,
        ("camera", "frame_feed"),
    ),
    "s9_navigation": _feature(
        "s9_navigation",
        "S9",
        "Pasywna nawigacja",
        "Odczyt istniejącego planu; ruch i osobne żądanie planowania w DISARMED są niedostępne.",
        "rider-navigate.target",
        (*MAP_UNITS, "rider-navigator.service"),
        ("camera", "frame_feed", "control"),
        can_move=True,
        control_owner="navigation",
    ),
    "s10_ai_providers": _feature(
        "s10_ai_providers",
        "S10",
        "Domena AI",
        "Uruchamia tylko wybraną domenę.",
        "rider-ai-provider.target",
        option_kind="provider",
    ),
    "s11_dev_mode": _feature(
        "s11_dev_mode",
        "S11",
        "Narzędzie deweloperskie",
        "Jedno narzędzie; Jupyter ręcznie.",
        "rider-dev.target",
        option_kind="tool",
    ),
}
DEFAULT_ALIASES = {
    "face_tracking": "s3_follow_me_face",
    "hand_tracking": "s3_follow_me_hand",
    "recon": "s4_recon",
    "follow_me": "s3_follow_me_face",
}

OPTION_SCHEMAS = {
    "tracking": {
        "field": "mode",
        "default": "face",
        "end_value": "none",
        "choices": [
            {"value": "face", "label": "Twarz — pasywnie", "label_en": "Face — passive"},
            {"value": "hand", "label": "Dłoń — pasywnie", "label_en": "Hand — passive"},
            {"value": "none", "label": "Zakończ obserwację", "label_en": "End observation"},
        ],
    },
    "voice": {
        "field": "domain",
        "default": "voice",
        "choices": [
            {"value": "voice", "label": "Pełny głos (ASR + chat + TTS)"},
            {"value": "asr", "label": "ASR"},
            {"value": "tts", "label": "TTS"},
        ],
    },
    "provider": {
        "field": "domain",
        "default": "text",
        "choices": [
            {"value": value, "label": label}
            for value, label in (
                ("text", "Tekst"),
                ("vision", "Wizja PC"),
                ("google", "Google"),
                ("voice", "Pełny głos (ASR + chat + TTS)"),
                ("asr", "ASR"),
                ("tts", "TTS"),
            )
        ],
    },
    "vision": {
        "field": "provider",
        "default": "local",
        "choices": [{"value": "local", "label": "Lokalnie Pi"}, {"value": "pc", "label": "Offload PC"}],
    },
    "tool": {
        "field": "tool",
        "default": "edge",
        "choices": [{"value": value, "label": value.upper()} for value in ("edge", "ssd", "raw")],
    },
}


def option_schema(feature: FeatureDefinition) -> dict | None:
    return OPTION_SCHEMAS.get(feature.option_kind)


def tracking_mode_for(feature: FeatureDefinition, options: dict | None = None) -> str | None:
    if feature.option_kind == "tracking":
        mode = (options or {}).get("mode", "face")
        if mode not in {"face", "hand", "none"}:
            raise ValueError("tracking mode must be face, hand or none")
        return mode
    return feature.tracking_mode


# (unit, id/alias, group, label, lifecycle, resources, can_move)
_ROWS = (
    ("rider-venom-perception.service", "venom_perception", "vision", "Venom floor observation", "on-demand", (), False),
    ("rider-api.service", "api", "core", "API", "startup", (), False),
    ("rider-broker.service", "broker", "core", "BUS", "startup", (), False),
    ("rider-web-bridge.service", "web-bridge", "core", "Web bridge", "startup", (), False),
    ("motion-executor.service", "motion-executor", "motion", "Executor / UART", "startup", ("uart",), True),
    ("sensor-reader.service", "sensor-reader", "motion", "Telemetria BUS", "startup", (), False),
    ("lcd-renderer.service", "lcd-renderer", "core", "LCD", "startup", ("lcd",), False),
    ("rider-boot-splash.service", "boot-splash", "core", "Boot splash", "startup", ("lcd",), False),
    ("wifi-unblock.service", "wifi-unblock", "core", "Wi-Fi radio", "startup", (), False),
    ("rider-minimal.target", "minimal-target", "core", "Minimal boot", "startup", (), False),
    ("rider-core.target", "core-target", "core", "Core", "startup", (), False),
    ("camera-capture@raw.service", "camera-capture-raw", "vision", "Kamera RAW", "on-demand", ("camera",), False),
    ("camera-capture@edge.service", "camera-capture-edge", "vision", "Kamera EDGE", "dev", ("camera",), False),
    ("camera-capture@ssd.service", "camera-capture-ssd", "vision", "Kamera SSD", "dev", ("camera",), False),
    ("frame-distributor.service", "frame-distributor", "vision", "Feed", "on-demand", ("frame_feed",), False),
    ("rider-vision.service", "vision", "vision", "Vision", "on-demand", (), False),
    ("rider-obstacle.service", "obstacle", "vision", "Przeszkody", "on-demand", (), False),
    ("rider-tracker.service", "tracker", "vision", "Tracker pasywny", "on-demand", (), False),
    (
        "rider-tracking-controller.service",
        "tracking-controller",
        "motion",
        "Follow controller",
        "on-demand",
        ("control",),
        True,
    ),
    (
        "rider-venom-navigation.service",
        "venom_navigation",
        "motion",
        "Venom bounded navigation",
        "on-demand",
        ("control",),
        True,
    ),
    ("rider-navigator.service", "navigator", "motion", "Nawigator", "on-demand", ("control",), True),
    ("rider-mapper.service", "mapper", "vision", "Mapa", "on-demand", (), False),
    ("rider-odometry.service", "odometry", "vision", "Odometria", "on-demand", (), False),
    (
        "rider-vision-offload.service",
        "vision-offload",
        "vision",
        "Offload obrazu",
        "on-demand",
        ("frame_feed",),
        False,
    ),
    ("rider-voice.service", "voice", "voice", "Pełna rozmowa CLI", "on-demand", ("mic", "speaker"), False),
    ("rider-voice-web.service", "voice-web", "voice", "Worker wybranej domeny ASR/TTS/chat", "on-demand", (), False),
    ("rider-google-bridge.service", "google-bridge", "cloud", "Google bridge", "on-demand", (), False),
    ("rider-choreographer.service", "choreographer", "motion", "Gesty", "on-demand", ("control",), True),
    ("jupyter.service", "jupyter", "dev", "Jupyter ręczny", "manual", (), False),
    ("audio-input.target", "audio-input", "voice", "Audio input", "on-demand", ("mic",), False),
    ("audio-output.target", "audio-output", "voice", "Audio output", "on-demand", ("speaker",), False),
)

UNIT_CATALOG = {}
for _unit, _id, _group, _label, _lifecycle, _resources, _moves in _ROWS:
    UNIT_CATALOG[_unit] = {
        "unit": _unit,
        "id": _id,
        "group": _group,
        "label": _label,
        "description": _label,
        "lifecycle": _lifecycle,
        "host": HOST,
        "can_move": _moves,
        "resources": list(_resources),
        "capabilities": ["read", "start", "stop", "restart"],
        "edges_out": [],
    }
for _task in DEFAULT_REGISTRY.values():
    _target = _task.services[0]
    if _target not in UNIT_CATALOG:
        UNIT_CATALOG[_target] = {
            "unit": _target,
            "id": _target[6:-7] + "-target",
            "group": "motion" if _task.can_move else "core",
            "label": _task.title,
            "description": _task.description,
            "lifecycle": "dev" if _task.option_kind == "tool" else "on-demand",
            "host": HOST,
            "can_move": _task.can_move,
            "resources": [],
            "edges_out": [],
            "capabilities": ["read", "start", "stop", "restart"],
        }

for _unit, _meta in UNIT_CATALOG.items():
    _meta["motion_owner"] = (
        "follow_me"
        if _unit in {"rider-tracking-controller.service", "rider-followme.target"}
        else "navigation"
        if _unit
        in {
            "rider-navigator.service",
            "rider-recon.target",
            "rider-navigate.target",
            "rider-venom-navigation.service",
            "rider-venom-navigation.target",
        }
        else "manual"
        if _meta["can_move"]
        else None
    )

_RUNTIME_MODULES = {
    "rider-api.service": ("flask", "PIL", "requests", "zmq"),
    "rider-broker.service": ("zmq",),
    "motion-executor.service": ("zmq", "serial"),
    "sensor-reader.service": ("zmq",),
    "rider-web-bridge.service": ("flask", "zmq"),
    "lcd-renderer.service": ("PIL",),
    "rider-boot-splash.service": ("PIL",),
    "camera-capture@raw.service": ("cv2", "numpy", "PIL", "zmq"),
    "camera-capture@edge.service": ("cv2", "numpy"),
    "camera-capture@ssd.service": ("cv2", "numpy", "PIL"),
    "frame-distributor.service": ("cv2", "numpy", "zmq"),
    "rider-tracker.service": ("cv2", "mediapipe", "zmq"),
    "rider-tracking-controller.service": ("zmq",),
    "rider-navigator.service": ("numpy", "zmq"),
    "rider-mapper.service": ("numpy", "zmq"),
    "rider-odometry.service": ("zmq",),
    "rider-vision.service": ("zmq",),
    "rider-obstacle.service": ("cv2", "numpy", "zmq"),
    "rider-vision-offload.service": ("cv2", "numpy", "zmq"),
    "rider-voice.service": ("requests",),
    "rider-voice-web.service": ("flask",),
}
for _unit, _meta in UNIT_CATALOG.items():
    _meta["runtime_modules"] = list(_RUNTIME_MODULES.get(_unit, ()))
    if sys.version_info < (3, 11) and _unit in {"rider-voice.service", "rider-voice-web.service"}:
        _meta["runtime_modules"].append("tomli")

# Python 3.9 is the device baseline. Catalog identifiers are stable HTTP identities.
UNIT_ALIASES = {meta["id"]: unit for unit, meta in UNIT_CATALOG.items()}
UNIT_ALIASES.update(
    {
        "web": "rider-web-bridge.service",
        "xgo": "motion-executor.service",
        "motion": "motion-executor.service",
        "motion-preview": "motion-executor.service",
        "sensors": "sensor-reader.service",
        "imu": "sensor-reader.service",
        "cam": CAMERA_UNITS[0],
        "camera": CAMERA_UNITS[0],
        "last": CAMERA_UNITS[0],
        "lastframe": CAMERA_UNITS[0],
        "edge": "camera-capture@edge.service",
        "ssd": "camera-capture@ssd.service",
        "offload": "rider-vision-offload.service",
        "pc-offload": "rider-vision-offload.service",
    }
)
CAMERA_CAPTURE_UNITS = frozenset((CAMERA_UNITS[0], "camera-capture@edge.service", "camera-capture@ssd.service"))
PROTECTED_UNITS = frozenset(
    (
        *BASE_UNITS,
        "rider-core.target",
        "rider-minimal.target",
        "wifi-unblock.service",
        "rider-boot-splash.service",
        "lcd-renderer.service",
    )
)


def task_domain(feature: FeatureDefinition, options: dict | None = None) -> str | None:
    """Use the catalog default for every selected-domain consumer."""
    if feature.option_kind not in {"voice", "provider"}:
        return None
    return (options or {}).get("domain", option_schema(feature)["default"])


def task_units(feature: FeatureDefinition, options: dict | None = None) -> tuple[str, ...]:
    """Resolve one minimal domain/tool. Invalid choices never fall back silently."""
    options = options or {}
    members = tuple(feature.members)
    kind = feature.option_kind
    allowed_keys = (
        {"provider"}
        if kind == "vision"
        else {"domain"}
        if kind in {"voice", "provider"}
        else {"tool"}
        if kind == "tool"
        else {"mode"}
        if kind == "tracking"
        else set()
    )
    if set(options) - allowed_keys:
        raise ValueError("unsupported task option")
    if kind == "tracking":
        tracking_mode_for(feature, options)
    if kind == "vision":
        provider = options.get("provider", "local")
        if provider not in {"local", "pc"}:
            raise ValueError("provider must be local or pc")
        members = (
            *CAMERA_UNITS,
            *(
                ("rider-vision.service", "rider-obstacle.service")
                if provider == "local"
                else ("rider-vision-offload.service",)
            ),
        )
    elif kind in {"voice", "provider"}:
        domain = task_domain(feature, options)
        domains = {
            "voice": ("rider-voice-web.service", "rider-voice.service"),
            "asr": ("rider-voice-web.service",),
            "tts": ("rider-voice-web.service",),
            "text": ("rider-voice-web.service",),
            "vision": (*CAMERA_UNITS, "rider-vision-offload.service"),
            "google": ("rider-google-bridge.service",),
        }
        if domain not in domains or (kind == "voice" and domain not in {"voice", "asr", "tts"}):
            raise ValueError("unsupported domain")
        members = domains[domain]
    elif kind == "tool":
        tool = options.get("tool", "edge")
        tools = {"edge": ("camera-capture@edge.service",), "ssd": ("camera-capture@ssd.service",), "raw": CAMERA_UNITS}
        if tool not in tools:
            raise ValueError("tool must be edge, ssd or raw; Jupyter is manual")
        members = tools[tool]
    if not members and feature.ensure_cam and not kind:
        members = CAMERA_UNITS
    from services.camera_pipeline_store import enabled

    if CAMERA_UNITS[0] in members and enabled():
        members = tuple(unit for unit in members if unit != "frame-distributor.service")
    return tuple(dict.fromkeys((*BASE_UNITS, *members, *feature.services)))


def task_resources(feature: FeatureDefinition, options: dict | None = None) -> tuple[str, ...]:
    units = task_units(feature, options)
    resources = {resource for unit in units for resource in UNIT_CATALOG.get(unit, {}).get("resources", [])}
    if feature.can_move:
        resources.add("control")
    if feature.option_kind in {"voice", "provider"}:
        domain = task_domain(feature, options)
        if domain in {"voice", "asr"}:
            resources.add("mic")
        if domain in {"voice", "tts"}:
            resources.add("speaker")
    return tuple(sorted(resources))


def catalog_payload() -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "catalog_version": CONTRACT_VERSION,
        "host": HOST,
        "source": "pi",
        "api_envelope_versions": [1],
        "api_media_type": "application/vnd.rider.api+json;version=1",
        "units": [{**meta, **unit_availability(unit)} for unit, meta in UNIT_CATALOG.items()],
        "features": [
            {
                **asdict(feature),
                "motion_owner": feature.control_owner,
                "option_schema": option_schema(feature),
                "members": list(task_units(feature)),
                "resources": list(task_resources(feature)),
            }
            for feature in DEFAULT_REGISTRY.values()
        ],
        "capabilities": ["task_lifecycle", "resource_consumers", "installed_state", "motion_gate", "domain_selection"],
    }


def unit_availability(unit: str) -> dict:
    """Implementation availability, separate from installation and ARM permission."""
    meta = UNIT_CATALOG.get(unit, {})
    if unit in {"rider-obstacle.service", "rider-obstacle.target"}:
        from services.camera_pipeline_store import enabled, snapshot

        if enabled() and snapshot()["profile"]["analysis_location"] != "local":
            return {"start_available": False, "start_unavailable_reason": "camera_pipeline_profile_conflict"}
    if unit in {"rider-venom-navigation.service", "rider-venom-navigation.target"}:
        from apps.safety.state import read_status

        if read_status().get("remote_decision_deadline_supported") is not True:
            return {"start_available": False, "start_unavailable_reason": "navigation_executor_update_required"}
    members = {member for rows in meta.get("task_members", {}).values() for member in rows}
    unavailable = unit == "rider-navigator.service" or "rider-navigator.service" in members
    return {
        "start_available": bool(meta) and not unavailable,
        "start_unavailable_reason": "navigation_traversal_unverified"
        if unavailable
        else None
        if meta
        else "unit_or_action_not_catalogued",
    }


def task_availability(feature: FeatureDefinition, options: dict | None = None) -> dict:
    from services.camera_pipeline_store import enabled, snapshot

    if (
        enabled()
        and snapshot()["profile"]["analysis_location"] == "local"
        and feature.name in {"s14_venom_navigation", "s15_venom_perception", "s12_venom_vision"}
    ):
        return {"start_available": False, "start_unavailable_reason": "camera_pipeline_local_analysis_selected"}
    if (
        enabled()
        and feature.name == "s7_obstacle_module"
        and (
            snapshot()["profile"]["analysis_location"] != "local" or (options or {}).get("provider", "local") != "local"
        )
    ):
        return {"start_available": False, "start_unavailable_reason": "camera_pipeline_profile_conflict"}
    available = compute_availability(feature.compute_tasks, legacy_goal=feature.name, options=options)
    if available is not None:
        return available
    for unit in task_units(feature, options):
        available = unit_availability(unit)
        if not available["start_available"]:
            return available
    return {"start_available": True, "start_unavailable_reason": None}


for _feature_definition in DEFAULT_REGISTRY.values():
    _target_metadata = UNIT_CATALOG[_feature_definition.services[0]]
    _target_metadata.setdefault("task_members", {})[_feature_definition.name] = [
        unit for unit in task_units(_feature_definition) if unit not in _feature_definition.services
    ]


def cli() -> None:
    """Read-only canonical allowlists for shell tools."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("units", "sync-units", "boot-units"))
    args = parser.parse_args()
    units = sorted(UNIT_CATALOG)
    if args.kind == "sync-units":
        units = sorted({unit.split("@", 1)[0] + "@.service" if "@" in unit else unit for unit in units})
    elif args.kind == "boot-units":
        units = list(BOOT_UNITS)
    print("\n".join(units))


if __name__ == "__main__":
    cli()
