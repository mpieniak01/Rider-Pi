# apps/voice/service.py
"""Voice assistant service facade - provides both class-based and functional APIs."""

from __future__ import annotations

# Re-export the new functional API
from .svc_core import run_listen, run_once

# Keep all existing exports for backward compatibility
from .service_impl import VoiceService, VoiceResult, SpeechTask, setup_signals

__all__ = ["run_listen", "run_once", "VoiceService", "VoiceResult", "SpeechTask", "setup_signals"]