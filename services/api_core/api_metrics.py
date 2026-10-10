"""Counters for interactive API calls, independent of route registration."""

from services.api_core import dashboard


def _update_api_metrics(path: str, status_code: int) -> None:
    """
    Zlicza wywołania API dla interaktywnych endpointów.
    Ignoruje endpointy systemowe, statusy, strumienie i monitoring.
    """
    # Pomijamy endpointy systemowe i monitorujące
    ignore_prefixes = (
        "/healthz",
        "/health",
        "/livez",
        "/readyz",
        "/state",
        "/sysinfo",
        "/metrics",
        "/events",
        "/camera/",
        "/snapshots/",
        "/vision/",
        "/api/status",
        "/api/devices",
        "/api/last_frame",
        "/api/metrics",
        "/api/app-metrics",  # sam siebie też ignorujemy
        "/api/bus/health",
        "/api/flags",
        "/api/version",
        "/api/navigator/status",  # status do odczytu
        "/web/",
        # "/",
        "/view",
        "/control",
        "/home",
        "/chat",
        "/system/",
        "/svc",
    )

    if path.startswith(ignore_prefixes):
        return

    # Określamy grupę API na podstawie ścieżki
    group = None
    if path.startswith(("/api/control", "/api/cmd")):
        group = "control"
    elif path.startswith("/api/navigator/"):
        # tylko interaktywne akcje (start/stop/config/return_home)
        if any(
            path.startswith(p)
            for p in [
                "/api/navigator/start",
                "/api/navigator/stop",
                "/api/navigator/config",
                "/api/navigator/return_home",
            ]
        ):
            group = "navigator"
    elif path.startswith("/api/voice/"):
        group = "voice"
    elif path.startswith("/api/home/"):
        # tylko command jest interaktywny
        if path.startswith("/api/home/command"):
            group = "google_home"
    elif path.startswith("/api/chat/send"):
        group = "chat"
    elif path.startswith(("/face/render", "/face/play", "/face/stop", "/api/draw/face")):
        group = "face"

    if group is None:
        return

    # Zliczamy (thread-safe) using centralized dashboard functions
    is_ok = status_code < 400
    if is_ok:
        dashboard.track_ok(group)
    else:
        dashboard.track_error(group)
