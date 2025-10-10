# apps/voice/svc_bus.py
"""Bus integration for voice service (UI state publishing and TTS speak subscription)."""

from __future__ import annotations

import queue
import threading
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .service_impl import SpeechTask
    from .voice_logging import VoiceLogger

# Bus (optional in runtime)
try:  # pragma: no cover - optional dependency
    from common.bus import BusPub, BusSub  # type: ignore
except Exception:  # pragma: no cover
    BusPub = None  # type: ignore[assignment]
    BusSub = None  # type: ignore[assignment]


class BusIntegrationMixin:
    """Mixin providing bus publishing and TTS speak subscription for VoiceService."""

    # Required attributes (defined in main service class)
    _bus_pub: Any | None
    _bus_sub: Any | None
    _bus_thread: threading.Thread | None
    _last_ui_state: str | None
    logger: VoiceLogger
    stop_event: threading.Event
    _speech_queue: queue.Queue[SpeechTask | None]
    _asr_cfg: Any  # ASRConfig

    # ─────────────────────────────────────────────────────────────────────────
    # Bus publishing

    def _publish_ui_state(self, state: str) -> None:
        if state == self._last_ui_state:
            return
        self._last_ui_state = state
        if not self._bus_pub:
            return
        try:
            self._bus_pub.publish("ui.state", {"state": state}, add_ts=True)
        except Exception as exc:
            self.logger.event("service.bus.state_failed", state=state, error=str(exc))

    def _publish_transcript(self, transcript: Any) -> None:  # transcript: Transcript
        if not self._bus_pub:
            return
        lang = (
            getattr(transcript, "language", None)
            or getattr(self._asr_cfg, "language", None)
            or getattr(self._asr_cfg, "lang", None)
            or "pl"
        )
        payload = {"text": transcript.text, "lang": lang}
        try:
            self._bus_pub.publish("audio.transcript", payload, add_ts=True)
        except Exception as exc:
            self.logger.event("service.bus.transcript_failed", error=str(exc))

    def _publish_assistant_speech(self, text: str) -> None:
        if not text or not self._bus_pub:
            return
        try:
            self._bus_pub.publish("assistant.speech", {"text": text}, add_ts=True)
        except Exception as exc:
            self.logger.event("service.bus.speech_failed", error=str(exc))

    # ─────────────────────────────────────────────────────────────────────────
    # TTS speak loop (bus subscription)

    def _tts_speak_loop(self) -> None:
        """Subscribe to tts.speak bus topic and queue speech tasks."""
        from .service_impl import SpeechTask

        sub = self._bus_sub
        if sub is None:
            return
        while not self.stop_event.is_set():
            try:
                topic, payload = sub.recv(timeout_ms=200)
            except Exception as exc:
                if self.stop_event.is_set():
                    break
                self.logger.event("service.bus.sub_error", error=str(exc))
                time.sleep(0.2)
                continue
            if not payload:
                continue
            text = payload.get("text") if isinstance(payload, dict) else None
            if not isinstance(text, str) or not text.strip():
                continue
            self._speech_queue.put(SpeechTask(text=text.strip(), source="bus", accumulate=False))
