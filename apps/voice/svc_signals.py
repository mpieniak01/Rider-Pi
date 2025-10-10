# apps/voice/svc_signals.py
"""Signal handling for voice service."""

from __future__ import annotations

import signal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service_impl import VoiceService


def setup_signals(service: VoiceService) -> None:
    """Setup SIGINT/SIGTERM handlers for graceful shutdown."""

    def handler(signum, frame):  # pragma: no cover
        service.logger.event("service.signal", signum=signum)
        service.stop()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
