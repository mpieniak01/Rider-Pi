# apps/voice/service.py
"""Voice assistant service loop."""
from __future__ import annotations

import signal
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from common.bus import BusPub

from . import logging as voice_logging
from .asr import ASRConfig, Transcript, transcribe
from .capture import AudioCapture, CaptureConfig
from .chat import ChatConfig, ChatSession
from .kws import HotwordConfig, HotwordDetector
from .nlu import Intent, NLUConfig, NLURouter
from .playback import PlaybackConfig, play_bytes, play_ding
from .tts import TTSConfig, synthesize
from .vad import WebRtcActivity, collect


@dataclass
class VoiceResult:
    transcript: Transcript
    intent: Intent
    reply: str
    latency_s: float
    audio: bytes | None
    audio_format: str
    sample_rate: int


class VoiceService:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.logger = voice_logging.get_logger("voice.service")
        self.stop_event = threading.Event()

        self._chat = ChatSession(ChatConfig(**config["chat"]))
        self._nlu = NLURouter(NLUConfig(**config["nlu"]))

        self._capture_cfg = CaptureConfig(**config["capture"])
        self._asr_cfg = ASRConfig(**config["asr"])

        allowed_tts = {"backend", "voice", "model", "format", "piper_model", "piper_config"}
        tts_kwargs = {k: v for k, v in config["tts"].items() if k in allowed_tts}
        self._tts_cfg = TTSConfig(**tts_kwargs)

        self._play_cfg = PlaybackConfig(**config["playback"])

        hotword_cfg = config.get("hotword", {})
        self._hotword = HotwordDetector(HotwordConfig(**hotword_cfg))
        self._hotword_engine = (hotword_cfg.get("engine") or "ptt").lower()
        self._hotword_enabled = bool(hotword_cfg.get("enabled", False))

        vad_cfg = config.get("vad", {})
        self._vad = WebRtcActivity(
            sample_rate=self._capture_cfg.sample_rate,
            mode=int(vad_cfg.get("mode", 3)),
            frame_ms=int(vad_cfg.get("frame_ms", self._capture_cfg.frame_ms)),
            tail_ms=int(vad_cfg.get("tail_ms", 350)),
            energy_gate=float(vad_cfg.get("energy_gate_dbfs", -40.0)),
        )
        self._max_len = int(vad_cfg.get("max_len_ms", 5000))

        service_cfg = config.get("service", {})
        self._save_audio = bool(service_cfg.get("save_audio", False))
        self._recordings_dir = Path(service_cfg.get("recordings_dir", "data/recordings"))
        ui_prefix = str(service_cfg.get("ui_bus_prefix", "voice.ui"))
        ui_topic = str(service_cfg.get("ui_state_topic", "state"))
        ui_warmup = int(service_cfg.get("ui_bus_warmup_ms", 0))
        self._ui_bus = BusPub(ui_prefix, warmup_ms=ui_warmup)
        self._ui_state_topic = ui_topic

    # ─────────────────────────────────────────────

    def stop(self) -> None:
        self.stop_event.set()

    def listen(self) -> None:
        self.logger.event("service.listen.start")
        try:
            while not self.stop_event.is_set():
                try:
                    self._cycle()
                except Exception as exc:
                    self.logger.error("service.cycle.error", error=str(exc))
                    self._publish_ui_state("idle")
                    time.sleep(0.3)
        finally:
            self.logger.event("service.listen.stop")

    def once(self, *, speak: bool = True) -> VoiceResult | None:
        try:
            return self._cycle(speak=speak)
        except Exception as exc:
            self.logger.error("service.once.error", error=str(exc))
            return None

    # ─────────────────────────────────────────────

    def _should_ding(self) -> bool:
        # PlaybackConfig może mieć sekcję ding; zachowaj ostrożność jeśli brak
        ding_cfg = getattr(self._play_cfg, "ding", None)
        return bool(getattr(ding_cfg, "enabled", True))

    def _play_start_ding(self) -> None:
        if self._should_ding():
            play_ding(self._play_cfg, self.logger)

    # Główna logika cyklu
    def _cycle(self, *, speak: bool = True) -> VoiceResult:
        self._publish_ui_state("hearing")
        queued_speech = False
        # PTT: czekamy na ENTER bez otwartego mikrofonu → gramy ding → dopiero potem nagrywamy
        try:
            if self._hotword_engine == "ptt" or (not self._hotword_enabled):
                if not self._wait_hotword_without_capture():
                    raise RuntimeError("Hotword/PTT timeout")
                if speak:
                    self._play_start_ding()
                audio = self._record_with_vad()
            else:
                # klasyczny hotword: potrzebuje audio do detekcji
                with AudioCapture(self._capture_cfg, self.logger) as capture:
                    if not self._hotword.wait(capture):
                        raise RuntimeError("Hotword timeout")
                    if speak:
                        self._play_start_ding()
                    # po ding zbieramy właściwe wypowiedzi
                    audio = collect(capture.frames(), self._vad, self._max_len)

            if not audio:
                raise RuntimeError("No audio captured")

            if self._save_audio:
                self._save_pcm(audio)

            start = time.time()
            transcript = transcribe(audio, self._capture_cfg.sample_rate, self._asr_cfg, self.logger)
            # widoczność transkryptu
            self.logger.event("service.asr.transcript", text=transcript.text)

            intent = self._nlu.route(transcript.text)
            reply = self._handle_intent(intent)

            reply_has_text = bool(reply.strip())
            if reply_has_text:
                audio_out, sample_rate, fmt = synthesize(reply, self._tts_cfg, self.logger)
            else:
                audio_out, sample_rate, fmt = None, 0, ""
                self.logger.event("service.reply.empty")

            if speak and audio_out:
                # nieblokujące odtwarzanie
                play_bytes(audio_out, fmt, self._play_cfg, self.logger, blocking=False)
                queued_speech = True
                self._publish_ui_state("speaking")

            latency = time.time() - start
            self.logger.event("service.cycle.done", latency=latency, intent=intent.kind)

            return VoiceResult(
                transcript=transcript,
                intent=intent,
                reply=reply,
                latency_s=latency,
                audio=audio_out,
                audio_format=fmt,
                sample_rate=sample_rate,
            )
        finally:
            if not queued_speech:
                self._publish_ui_state("idle")

    # ─────────────────────────────────────────────

    def _wait_hotword_without_capture(self) -> bool:
        """PTT/keyboard: czekaj na wyzwolenie bez otwartego mikrofonu."""
        # większość implementacji HotwordDetector.ignoreuje argument capture w trybie 'ptt';
        # przekazujemy None dla czytelności.
        try:
            return bool(self._hotword.wait(None))
        except TypeError:
            # starszy podpis wymaga 1 parametru; przekaż atrapu
            class _NullCap:
                def frames(self):  # pragma: no cover
                    if False:
                        yield b""
            return bool(self._hotword.wait(_NullCap()))

    def _record_with_vad(self) -> bytes:
        """Otwórz mikrofon dopiero po sygnale startowym i zbierz wypowiedź VAD-em."""
        with AudioCapture(self._capture_cfg, self.logger) as capture:
            return collect(capture.frames(), self._vad, self._max_len)

    def _handle_intent(self, intent: Intent) -> str:
        if intent.kind == "command":
            name = intent.payload.get("name", "command")
            self.logger.event("service.command", name=name)
            return f"Wykonuję: {name}."
        reply, _ = self._chat.ask(intent.payload.get("text", ""))
        return reply

    def _save_pcm(self, audio: bytes) -> None:
        self._recordings_dir.mkdir(parents=True, exist_ok=True)
        # użyj czasu z dokładnością do ms, by uniknąć kolizji nazw
        ts = time.time()
        filename = f"capture_{int(ts)}_{int((ts % 1)*1000):03d}.wav"
        path = self._recordings_dir / filename
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._capture_cfg.sample_rate)
            wf.writeframes(audio)
        self.logger.event("service.audio.saved", path=str(path))

    def _publish_ui_state(self, state: str) -> None:
        try:
            self._ui_bus.publish(self._ui_state_topic, {"state": state}, add_ts=True)
        except Exception as exc:
            self.logger.debug("service.ui.publish_failed", error=str(exc))

# ─────────────────────────────────────────────

def setup_signals(service: VoiceService) -> None:
    def handler(signum, frame):  # pragma: no cover - signal handler
        service.logger.event("service.signal", signum=signum)
        service.stop()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
