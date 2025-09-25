from __future__ import annotations

# Legacy class-based API (dla kompatybilności z testami)
from .service_impl import SpeechTask, VoiceResult, VoiceService, setup_signals

# Public functional API (nowe)
from .svc_core import run_listen, run_once

__all__ = ['run_listen', 'run_once', 'VoiceService', 'VoiceResult', 'SpeechTask', 'setup_signals']
