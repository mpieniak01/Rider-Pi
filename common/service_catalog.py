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

# Stable systemd identities shared by catalog definitions and runtime projections.
SERVICE_CAMERA_CAPTURE_EDGE = "camera-capture@edge.service"
SERVICE_CAMERA_CAPTURE_RAW = "camera-capture@raw.service"
SERVICE_CAMERA_CAPTURE_SSD = "camera-capture@ssd.service"
SERVICE_FRAME_DISTRIBUTOR = "frame-distributor.service"
SERVICE_LCD_RENDERER = "lcd-renderer.service"
SERVICE_MOTION_EXECUTOR = "motion-executor.service"
SERVICE_RIDER_API = "rider-api.service"
SERVICE_RIDER_BOOT_SPLASH = "rider-boot-splash.service"
SERVICE_RIDER_BROKER = "rider-broker.service"
TARGET_RIDER_CORE = "rider-core.target"
TARGET_RIDER_FOLLOWME = "rider-followme.target"
SERVICE_RIDER_MAPPER = "rider-mapper.service"
TARGET_RIDER_MINIMAL = "rider-minimal.target"
SERVICE_RIDER_NAVIGATOR = "rider-navigator.service"
SERVICE_RIDER_OBSTACLE = "rider-obstacle.service"
SERVICE_RIDER_ODOMETRY = "rider-odometry.service"
SERVICE_RIDER_TRACKER = "rider-tracker.service"
SERVICE_RIDER_TRACKING_CONTROLLER = "rider-tracking-controller.service"
SERVICE_RIDER_VENOM_NAVIGATION = "rider-venom-navigation.service"
SERVICE_RIDER_VISION_OFFLOAD = "rider-vision-offload.service"
SERVICE_RIDER_VISION = "rider-vision.service"
SERVICE_RIDER_VOICE_WEB = "rider-voice-web.service"
SERVICE_RIDER_VOICE = "rider-voice.service"
SERVICE_RIDER_WEB_BRIDGE = "rider-web-bridge.service"
SERVICE_SENSOR_READER = "sensor-reader.service"
SERVICE_WIFI_UNBLOCK = "wifi-unblock.service"
BOOT_UNITS = (TARGET_RIDER_MINIMAL, SERVICE_RIDER_BOOT_SPLASH, SERVICE_LCD_RENDERER, SERVICE_WIFI_UNBLOCK)


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
    SERVICE_RIDER_BROKER,
    SERVICE_RIDER_API,
    SERVICE_MOTION_EXECUTOR,
    SERVICE_SENSOR_READER,
    SERVICE_RIDER_WEB_BRIDGE,
)
CAMERA_UNITS = (SERVICE_CAMERA_CAPTURE_RAW, SERVICE_FRAME_DISTRIBUTOR)
MAP_UNITS = (
    *CAMERA_UNITS,
    SERVICE_RIDER_VISION,
    SERVICE_RIDER_OBSTACLE,
    SERVICE_RIDER_ODOMETRY,
    SERVICE_RIDER_MAPPER,
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
        "s0_core", "S0", "Baza / odczyt", "API i telemetria, bez zgody na napędy.", TARGET_RIDER_CORE, BASE_UNITS
    ),
    "s1_manual": _feature(
        "s1_manual",
        "S1",
        "Sterowanie ręczne",
        "Wymaga osobnego uzbrojenia operatora.",
        TARGET_RIDER_CORE,
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
        TARGET_RIDER_CORE,
        CAMERA_UNITS,
        ("camera", "frame_feed"),
    ),
    "s3_follow_me_face": _feature(
        "s3_follow_me_face",
        "S3",
        "Follow Me — twarz",
        "Śledzenie z napędami.",
        TARGET_RIDER_FOLLOWME,
        (*CAMERA_UNITS, SERVICE_RIDER_TRACKER, SERVICE_RIDER_TRACKING_CONTROLLER),
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
        TARGET_RIDER_FOLLOWME,
        (*CAMERA_UNITS, SERVICE_RIDER_TRACKER, SERVICE_RIDER_TRACKING_CONTROLLER),
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
        (*MAP_UNITS, SERVICE_RIDER_NAVIGATOR),
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
        (*CAMERA_UNITS, SERVICE_RIDER_TRACKER),
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
        (*MAP_UNITS, SERVICE_RIDER_NAVIGATOR),
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
    (SERVICE_RIDER_API, "api", "core", "API", "startup", (), False),
    (SERVICE_RIDER_BROKER, "broker", "core", "BUS", "startup", (), False),
    (SERVICE_RIDER_WEB_BRIDGE, "web-bridge", "core", "Web bridge", "startup", (), False),
    (SERVICE_MOTION_EXECUTOR, "motion-executor", "motion", "Executor / UART", "startup", ("uart",), True),
    (SERVICE_SENSOR_READER, "sensor-reader", "motion", "Telemetria BUS", "startup", (), False),
    (SERVICE_LCD_RENDERER, "lcd-renderer", "core", "LCD", "startup", ("lcd",), False),
    (SERVICE_RIDER_BOOT_SPLASH, "boot-splash", "core", "Boot splash", "startup", ("lcd",), False),
    (SERVICE_WIFI_UNBLOCK, "wifi-unblock", "core", "Wi-Fi radio", "startup", (), False),
    (TARGET_RIDER_MINIMAL, "minimal-target", "core", "Minimal boot", "startup", (), False),
    (TARGET_RIDER_CORE, "core-target", "core", "Core", "startup", (), False),
    (SERVICE_CAMERA_CAPTURE_RAW, "camera-capture-raw", "vision", "Kamera RAW", "on-demand", ("camera",), False),
    (SERVICE_CAMERA_CAPTURE_EDGE, "camera-capture-edge", "vision", "Kamera EDGE", "dev", ("camera",), False),
    (SERVICE_CAMERA_CAPTURE_SSD, "camera-capture-ssd", "vision", "Kamera SSD", "dev", ("camera",), False),
    (SERVICE_FRAME_DISTRIBUTOR, "frame-distributor", "vision", "Feed", "on-demand", ("frame_feed",), False),
    (SERVICE_RIDER_VISION, "vision", "vision", "Vision", "on-demand", (), False),
    (SERVICE_RIDER_OBSTACLE, "obstacle", "vision", "Przeszkody", "on-demand", (), False),
    (SERVICE_RIDER_TRACKER, "tracker", "vision", "Tracker pasywny", "on-demand", (), False),
    (
        SERVICE_RIDER_TRACKING_CONTROLLER,
        "tracking-controller",
        "motion",
        "Follow controller",
        "on-demand",
        ("control",),
        True,
    ),
    (
        SERVICE_RIDER_VENOM_NAVIGATION,
        "venom_navigation",
        "motion",
        "Venom bounded navigation",
        "on-demand",
        ("control",),
        True,
    ),
    (SERVICE_RIDER_NAVIGATOR, "navigator", "motion", "Nawigator", "on-demand", ("control",), True),
    (SERVICE_RIDER_MAPPER, "mapper", "vision", "Mapa", "on-demand", (), False),
    (SERVICE_RIDER_ODOMETRY, "odometry", "vision", "Odometria", "on-demand", (), False),
    (
        SERVICE_RIDER_VISION_OFFLOAD,
        "vision-offload",
        "vision",
        "Offload obrazu",
        "on-demand",
        ("frame_feed",),
        False,
    ),
    (SERVICE_RIDER_VOICE, "voice", "voice", "Pełna rozmowa CLI", "on-demand", ("mic", "speaker"), False),
    (SERVICE_RIDER_VOICE_WEB, "voice-web", "voice", "Worker wybranej domeny ASR/TTS/chat", "on-demand", (), False),
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
        if _unit in {SERVICE_RIDER_TRACKING_CONTROLLER, TARGET_RIDER_FOLLOWME}
        else "navigation"
        if _unit
        in {
            SERVICE_RIDER_NAVIGATOR,
            "rider-recon.target",
            "rider-navigate.target",
            SERVICE_RIDER_VENOM_NAVIGATION,
            "rider-venom-navigation.target",
        }
        else "manual"
        if _meta["can_move"]
        else None
    )

_RUNTIME_MODULES = {
    SERVICE_RIDER_API: ("flask", "PIL", "requests", "zmq"),
    SERVICE_RIDER_BROKER: ("zmq",),
    SERVICE_MOTION_EXECUTOR: ("zmq", "serial"),
    SERVICE_SENSOR_READER: ("zmq",),
    SERVICE_RIDER_WEB_BRIDGE: ("flask", "zmq"),
    SERVICE_LCD_RENDERER: ("PIL",),
    SERVICE_RIDER_BOOT_SPLASH: ("PIL",),
    SERVICE_CAMERA_CAPTURE_RAW: ("cv2", "numpy", "PIL", "zmq"),
    SERVICE_CAMERA_CAPTURE_EDGE: ("cv2", "numpy"),
    SERVICE_CAMERA_CAPTURE_SSD: ("cv2", "numpy", "PIL"),
    SERVICE_FRAME_DISTRIBUTOR: ("cv2", "numpy", "zmq"),
    SERVICE_RIDER_TRACKER: ("cv2", "mediapipe", "zmq"),
    SERVICE_RIDER_TRACKING_CONTROLLER: ("zmq",),
    SERVICE_RIDER_NAVIGATOR: ("numpy", "zmq"),
    SERVICE_RIDER_MAPPER: ("numpy", "zmq"),
    SERVICE_RIDER_ODOMETRY: ("zmq",),
    SERVICE_RIDER_VISION: ("zmq",),
    SERVICE_RIDER_OBSTACLE: ("cv2", "numpy", "zmq"),
    SERVICE_RIDER_VISION_OFFLOAD: ("cv2", "numpy", "zmq"),
    SERVICE_RIDER_VOICE: ("requests",),
    SERVICE_RIDER_VOICE_WEB: ("flask",),
}
for _unit, _meta in UNIT_CATALOG.items():
    _meta["runtime_modules"] = list(_RUNTIME_MODULES.get(_unit, ()))
    if sys.version_info < (3, 11) and _unit in {SERVICE_RIDER_VOICE, SERVICE_RIDER_VOICE_WEB}:
        _meta["runtime_modules"].append("tomli")

# Python 3.9 is the device baseline. Catalog identifiers are stable HTTP identities.
UNIT_ALIASES = {meta["id"]: unit for unit, meta in UNIT_CATALOG.items()}
UNIT_ALIASES.update(
    {
        "web": SERVICE_RIDER_WEB_BRIDGE,
        "xgo": SERVICE_MOTION_EXECUTOR,
        "motion": SERVICE_MOTION_EXECUTOR,
        "motion-preview": SERVICE_MOTION_EXECUTOR,
        "sensors": SERVICE_SENSOR_READER,
        "imu": SERVICE_SENSOR_READER,
        "cam": CAMERA_UNITS[0],
        "camera": CAMERA_UNITS[0],
        "last": CAMERA_UNITS[0],
        "lastframe": CAMERA_UNITS[0],
        "edge": SERVICE_CAMERA_CAPTURE_EDGE,
        "ssd": SERVICE_CAMERA_CAPTURE_SSD,
        "offload": SERVICE_RIDER_VISION_OFFLOAD,
        "pc-offload": SERVICE_RIDER_VISION_OFFLOAD,
    }
)
CAMERA_CAPTURE_UNITS = frozenset((CAMERA_UNITS[0], SERVICE_CAMERA_CAPTURE_EDGE, SERVICE_CAMERA_CAPTURE_SSD))
PROTECTED_UNITS = frozenset(
    (
        *BASE_UNITS,
        TARGET_RIDER_CORE,
        TARGET_RIDER_MINIMAL,
        SERVICE_WIFI_UNBLOCK,
        SERVICE_RIDER_BOOT_SPLASH,
        SERVICE_LCD_RENDERER,
    )
)


def task_domain(feature: FeatureDefinition, options: dict | None = None) -> str | None:
    """Use the catalog default for every selected-domain consumer."""
    if feature.option_kind not in {"voice", "provider"}:
        return None
    return (options or {}).get("domain", option_schema(feature)["default"])


def _vision_task_members(options):
    provider = options.get("provider", "local")
    if provider not in {"local", "pc"}:
        raise ValueError("provider must be local or pc")
    analysis = (
        (SERVICE_RIDER_VISION, SERVICE_RIDER_OBSTACLE) if provider == "local" else (SERVICE_RIDER_VISION_OFFLOAD,)
    )
    return (*CAMERA_UNITS, *analysis)


def _domain_task_members(feature, options):
    domain = task_domain(feature, options)
    domains = {
        "voice": (SERVICE_RIDER_VOICE_WEB, SERVICE_RIDER_VOICE),
        "asr": (SERVICE_RIDER_VOICE_WEB,),
        "tts": (SERVICE_RIDER_VOICE_WEB,),
        "text": (SERVICE_RIDER_VOICE_WEB,),
        "vision": (*CAMERA_UNITS, SERVICE_RIDER_VISION_OFFLOAD),
        "google": ("rider-google-bridge.service",),
    }
    if domain not in domains or (feature.option_kind == "voice" and domain not in {"voice", "asr", "tts"}):
        raise ValueError("unsupported domain")
    return domains[domain]


def _tool_task_members(options):
    tool = options.get("tool", "edge")
    tools = {"edge": (SERVICE_CAMERA_CAPTURE_EDGE,), "ssd": (SERVICE_CAMERA_CAPTURE_SSD,), "raw": CAMERA_UNITS}
    if tool not in tools:
        raise ValueError("tool must be edge, ssd or raw; Jupyter is manual")
    return tools[tool]


def _selected_task_members(feature, options, members):
    if feature.option_kind == "vision":
        return _vision_task_members(options)
    if feature.option_kind in {"voice", "provider"}:
        return _domain_task_members(feature, options)
    if feature.option_kind == "tool":
        return _tool_task_members(options)
    return members


def task_units(feature: FeatureDefinition, options: dict | None = None) -> tuple[str, ...]:
    """Resolve one minimal domain/tool. Invalid choices never fall back silently."""
    options = options or {}
    members = tuple(feature.members)
    kind = feature.option_kind
    allowed_keys = {
        "vision": {"provider"},
        "voice": {"domain"},
        "provider": {"domain"},
        "tool": {"tool"},
        "tracking": {"mode"},
    }
    if set(options) - allowed_keys.get(kind, set()):
        raise ValueError("unsupported task option")
    if kind == "tracking":
        tracking_mode_for(feature, options)
    members = _selected_task_members(feature, options, members)
    if not members and feature.ensure_cam and not kind:
        members = CAMERA_UNITS
    from services.camera_pipeline_store import enabled

    if CAMERA_UNITS[0] in members and enabled():
        members = tuple(unit for unit in members if unit != SERVICE_FRAME_DISTRIBUTOR)
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
    if unit in {SERVICE_RIDER_OBSTACLE, "rider-obstacle.target"}:
        from services.camera_pipeline_store import enabled, snapshot

        if enabled() and snapshot()["profile"]["analysis_location"] != "local":
            return {"start_available": False, "start_unavailable_reason": "camera_pipeline_profile_conflict"}
    if unit in {SERVICE_RIDER_VENOM_NAVIGATION, "rider-venom-navigation.target"}:
        from apps.safety.state import read_status

        if read_status().get("remote_decision_deadline_supported") is not True:
            return {"start_available": False, "start_unavailable_reason": "navigation_executor_update_required"}
    members = {member for rows in meta.get("task_members", {}).values() for member in rows}
    unavailable = unit == SERVICE_RIDER_NAVIGATOR or SERVICE_RIDER_NAVIGATOR in members
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
