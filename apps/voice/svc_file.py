# apps/voice/svc_file.py
"""Voice service file mode pipeline - listen/once functionality moved 1:1 from service.py."""

from __future__ import annotations

from typing import Any


def run_listen_file(cfg: dict[str, Any], args) -> int:
    """Run listen mode using file-based pipeline (moved 1:1 from service.py)."""
    # Import here to avoid circular imports
    from .service_impl import VoiceService, setup_signals

    service = VoiceService(cfg)
    setup_signals(service)
    service.listen()
    return 0


def run_once_file(cfg: dict[str, Any], args) -> int:
    """Run once mode using file-based pipeline (moved 1:1 from service.py)."""
    # Import here to avoid circular imports
    from .service_impl import VoiceService, setup_signals

    service = VoiceService(cfg)
    setup_signals(service)
    result = service.once()
    if result:
        print(result.transcript.text)
    return 0
