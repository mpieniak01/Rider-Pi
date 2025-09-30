# apps/voice/svc_file_pipeline.py
"""File-based ASR→CHAT→TTS pipeline logic.

Extracted from service_impl.py to keep files under 600 lines.
Contains the core voice processing cycle for file mode operation.
"""

from __future__ import annotations

import audioop
import time
from collections.abc import Iterable
from typing import Any

from .asr import ASRConfig, transcribe
from .capture import AudioCapture, CaptureConfig
from .chat import ChatConfig
from .kws import HotwordDetector
from .nlu import Intent, NLURouter
from .playback import PlaybackConfig, play_ding
from .tts import TTSConfig, TTSStreamResult
from .vad import WebRtcActivity, collect


class VoiceProcessingPipeline:
    """Handles the complete voice processing pipeline for file mode."""

    def __init__(
        self,
        capture_cfg: CaptureConfig,
        asr_cfg: ASRConfig,
        chat_cfg: ChatConfig,
        tts_cfg: TTSConfig,
        play_cfg: PlaybackConfig,
        nlu: NLURouter,
        hotword: HotwordDetector,
        vad: WebRtcActivity,
        logger: Any,
        config: dict[str, Any],
    ):
        self.capture_cfg = capture_cfg
        self.asr_cfg = asr_cfg
        self.chat_cfg = chat_cfg
        self.tts_cfg = tts_cfg
        self.play_cfg = play_cfg
        self.nlu = nlu
        self.hotword = hotword
        self.vad = vad
        self.logger = logger
        self.config = config

        # Timing and behavior settings
        self.hotword_enabled = config.get("hotword_enabled", True)
        self.hotword_engine = config.get("hotword_engine", "")
        self.beep_enabled = config.get("beep_enabled", True)
        self.beep_pause_ms = config.get("beep_pause_ms", 300)
        self.beep_delay_ms = config.get("beep_delay_ms", 0)
        self.mic_open_delay_ms = config.get("mic_open_delay_ms", 0)
        self.post_tts_mute_ms = config.get("post_tts_mute_ms", 500)
        self.max_len = config.get("max_len", 30.0)
        self.save_audio = config.get("save_audio", False)

        # State tracking
        self.mute_until_ts = 0.0
        self.last_ding_ts = 0.0

    def execute_cycle(self, *, speak: bool = True, publish_ui_state: Any = None) -> dict[str, Any]:
        """Execute one complete voice processing cycle.

        Returns:
            Dictionary containing cycle results (transcript, intent, reply, etc.)
        """
        if publish_ui_state:
            publish_ui_state("hearing")

        # Wait for mute period to end
        now = time.time()
        if now < self.mute_until_ts:
            time.sleep(self.mute_until_ts - now)

        # Reset VAD for new cycle
        try:
            self.vad.reset()
        except Exception:
            pass

        # Determine input method
        waiting_without_capture = self.hotword_engine == "ptt" or (not self.hotword_enabled)

        if waiting_without_capture:
            if not self._wait_hotword_without_capture():
                if publish_ui_state:
                    publish_ui_state("idle")
                raise RuntimeError("Hotword/PTT timeout")

            if speak and self._should_ding():
                play_ding(self.play_cfg, self.logger)
                self.last_ding_ts = time.time()
                self.mute_until_ts = max(self.mute_until_ts, time.time() + (self.beep_pause_ms / 1000.0))
                if self.beep_delay_ms > 0:
                    time.sleep(self.beep_delay_ms / 1000.0)

            audio = self._record_with_vad()
        else:
            with AudioCapture(self.capture_cfg, self.logger) as capture:
                if not self.hotword.wait(capture):
                    if publish_ui_state:
                        publish_ui_state("idle")
                    raise RuntimeError("Hotword timeout")

                if speak and self._should_ding():
                    play_ding(self.play_cfg, self.logger)
                    self.last_ding_ts = time.time()
                    self.mute_until_ts = max(self.mute_until_ts, time.time() + (self.beep_pause_ms / 1000.0))
                    if self.beep_delay_ms > 0:
                        time.sleep(self.beep_delay_ms / 1000.0)

                if self.mic_open_delay_ms > 0:
                    time.sleep(self.mic_open_delay_ms / 1000.0)

                audio = collect(capture.frames(), self.vad, self.max_len)

        # Check for silence after beep
        if not audio:
            if publish_ui_state:
                publish_ui_state("idle")
            raise RuntimeError("No audio captured")

        if self.save_audio:
            self._save_pcm(audio)

        # Processing phase
        if publish_ui_state:
            publish_ui_state("thinking")

        start = time.time()

        # ASR: Speech to text
        transcript = transcribe(audio, self.capture_cfg.sample_rate, self.asr_cfg, self.logger)
        self.logger.event("service.asr.transcript", text=transcript.text)

        # NLU: Intent recognition
        intent = self.nlu.route(transcript.text)

        # Chat: Generate response
        reply = self._handle_intent(intent)
        reply_text = reply.strip()

        # TTS: Text to speech
        speech_result: TTSStreamResult | None = None
        if speak and reply_text:
            speech_result = speak(
                reply_text,
                self.tts_cfg,
                self.play_cfg,
                self.logger,
                accumulate=True,
            )

        total_latency = time.time() - start
        self.logger.event(
            "service.cycle.done",
            latency=total_latency,
            intent=intent.kind,
        )

        # Post-processing cooldown for PTT
        if self.hotword_engine == "ptt":
            if self.post_tts_mute_ms > 0:
                time.sleep(self.post_tts_mute_ms / 1000.0)
            time.sleep(0.15)
            try:
                import sys
                import termios

                termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
            except Exception:
                pass

        # Extract audio result data
        audio_bytes = speech_result.audio if (speech_result and speech_result.audio) else None
        audio_format = speech_result.audio_format if speech_result else ""
        sample_rate = speech_result.sample_rate if speech_result else 0

        if not speak or not reply_text:
            if publish_ui_state:
                publish_ui_state("idle")

        return {
            "transcript": transcript,
            "intent": intent,
            "reply": reply,
            "latency_s": total_latency,
            "audio": audio_bytes,
            "audio_format": audio_format,
            "sample_rate": sample_rate,
        }

    def _should_ding(self) -> bool:
        """Check if ding should be played."""
        if not self.beep_enabled:
            return False

        # Check PlaybackConfig.ding settings
        ding_cfg = getattr(self.play_cfg, "ding", None)
        if isinstance(ding_cfg, dict):
            ok = bool(ding_cfg.get("enabled", True))
        else:
            ok = True

        # Cooldown check (≥1.0 s)
        if ok and (time.time() - self.last_ding_ts) < 1.0:
            return False
        return ok

    def _wait_hotword_without_capture(self) -> bool:
        """Wait for hotword/PTT trigger without opening microphone."""
        if self.hotword_engine == "ptt":
            try:
                return bool(self.hotword.wait_ptt(timeout=60.0))  # type: ignore[attr-defined]
            except AttributeError:
                try:
                    return bool(self.hotword.wait(None))
                except TypeError:

                    class _NullCap:
                        def frames(self) -> Iterable[bytes]:  # pragma: no cover
                            if False:
                                yield b""

                    return bool(self.hotword.wait(_NullCap()))

        try:
            return bool(self.hotword.wait(None))
        except TypeError:

            class _NullCap:
                def frames(self) -> Iterable[bytes]:  # pragma: no cover
                    if False:
                        yield b""

            return bool(self.hotword.wait(_NullCap()))

    def _record_with_vad(self) -> bytes:
        """Record audio with VAD detection."""
        # This is a placeholder - actual implementation would be in the calling code
        # or imported from svc_audio module
        with AudioCapture(self.capture_cfg, self.logger) as capture:
            return collect(capture.frames(), self.vad, self.max_len)

    def _handle_intent(self, intent: Intent) -> str:
        """Handle intent and generate response."""
        # This is a placeholder - actual implementation depends on chat system
        # For now, return a simple response
        return f"Processed intent: {intent.kind}"

    def _save_pcm(self, audio: bytes) -> None:
        """Save audio data to file for debugging."""
        import tempfile
        import time

        timestamp = int(time.time())
        try:
            with tempfile.NamedTemporaryFile(prefix=f"voice_audio_{timestamp}_", suffix=".pcm", delete=False) as f:
                f.write(audio)
                self.logger.event("audio.saved", path=f.name, size=len(audio))
        except Exception as e:
            self.logger.event("audio.save_error", error=str(e))

    def _frame_has_voice(self, frame: bytes, thr: int) -> bool:
        """Simple RMS energy indicator for voice detection."""
        try:
            rms = audioop.rms(frame, 2)  # 16-bit
            return rms >= thr
        except Exception:
            return False
