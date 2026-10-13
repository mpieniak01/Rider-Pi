"""Compute goal definitions and availability shared by the Pi service catalog."""

from __future__ import annotations

EN = {
    "s14_venom_navigation": (
        "Venom bounded navigation",
        "Remote floor perception and expiring movement; explicit navigation ARM required.",
    ),
    "s12_venom_vision": ("Venom scene description", "Observe the camera scene; no obstacle or motion clearance."),
    "s13_venom_voice": ("Venom conversation", "Microphone, Venom STT/text/TTS and Pi playback; no motion tools."),
}


def compute_features(feature, camera_units):
    return {
        "s14_venom_navigation": feature(
            "s14_venom_navigation",
            "S14",
            "Pętla ruchu Venom",
            "Zdalna percepcja; utrata świeżej decyzji zatrzymuje ruch. Osobne uzbrojenie navigation.",
            "rider-ai-provider.target",
            (*camera_units, "rider-venom-navigation.service"),
            ("camera", "frame_feed", "control"),
            can_move=True,
            control_owner="navigation",
        ),
        "s12_venom_vision": feature(
            "s12_venom_vision",
            "S12",
            "Opis sceny w Venomie",
            "Obserwacja kamery; bez oceny przeszkód i zgody na przejazd.",
            "rider-ai-provider.target",
            (*camera_units, "rider-vision-offload.service"),
            ("camera", "frame_feed"),
            compute_tasks=("vision.describe",),
        ),
        "s13_venom_voice": feature(
            "s13_venom_voice",
            "S13",
            "Rozmowa przez Venom",
            "Mikrofon, STT/tekst/TTS Venoma i odtwarzanie na Pi; bez narzędzi ruchu.",
            "rider-voice.target",
            ("rider-voice.service",),
            ("mic", "speaker"),
            compute_tasks=("audio.transcribe", "text.respond", "audio.synthesize"),
        ),
    }


def compute_availability(tasks):
    if tasks:
        from services import compute_config

        try:
            executor = compute_config.selected_executor()
        except (ValueError, OSError):
            executor = None
        if executor is None or set(tasks) - set(executor["tasks"]):
            return {"start_available": False, "start_unavailable_reason": "compute_executor_unavailable"}
    return None
