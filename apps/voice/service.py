"""Voice assistant service loop."""
from __future__ import annotations

import signal
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
        self._tts_cfg = TTSConfig(**config["tts"])
        self._play_cfg = PlaybackConfig(**config["playback"])
        hotword_cfg = config.get("hotword", {})
        self._hotword = HotwordDetector(HotwordConfig(**hotword_cfg))
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

    def stop(self) -> None:
        self.stop_event.set()

    def listen(self) -> None:
        self.logger.event("service.listen.start")
        while not self.stop_event.is_set():
            try:
                self._cycle()
            except Exception as exc:
                self.logger.error("service.cycle.error", error=str(exc))
                time.sleep(1.0)
        self.logger.event("service.listen.stop")

    def once(self, *, speak: bool = True) -> VoiceResult | None:
        try:
            return self._cycle(speak=speak)
        except Exception as exc:
            self.logger.error("service.once.error", error=str(exc))
            return None

    def _cycle(self, *, speak: bool = True) -> VoiceResult:
        with AudioCapture(self._capture_cfg, self.logger) as capture:
            if not self._hotword.wait(capture):
                raise RuntimeError("Hotword timeout")
            if speak:
                play_ding(self._play_cfg, self.logger)
            audio = collect(capture.frames(), self._vad, self._max_len)
        if not audio:
            raise RuntimeError("No audio captured")
        if self._save_audio:
            self._save_pcm(audio)
        start = time.time()
        transcript = transcribe(audio, self._capture_cfg.sample_rate, self._asr_cfg, self.logger)
        intent = self._nlu.route(transcript.text)
        reply = self._handle_intent(intent)
        audio_out, sample_rate, fmt = synthesize(reply, self._tts_cfg, self.logger)
        if speak:
            play_bytes(audio_out, fmt, self._play_cfg, self.logger, blocking=False)
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

    def _handle_intent(self, intent: Intent) -> str:
        if intent.kind == "command":
            name = intent.payload.get("name", "command")
            self.logger.event("service.command", name=name)
            return f"Executing {name}."
        reply, _ = self._chat.ask(intent.payload.get("text", ""))
        return reply

    def _save_pcm(self, audio: bytes) -> None:
        self._recordings_dir.mkdir(parents=True, exist_ok=True)
        path = self._recordings_dir / f"capture_{int(time.time())}.wav"
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._capture_cfg.sample_rate)
            wf.writeframes(audio)
        self.logger.event("service.audio.saved", path=str(path))


def setup_signals(service: VoiceService) -> None:
    def handler(signum, frame):  # pragma: no cover - signal handler
        service.logger.event("service.signal", signum=signum)
        service.stop()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
