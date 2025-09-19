# apps/voice/service.py
"""Voice assistant service loop."""
from __future__ import annotations

import contextlib
import queue
import signal
import subprocess
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

try:  # pragma: no cover - optional dependency
    from common.bus import BusPub as RuntimeBusPub
except Exception:  # pragma: no cover - optional dependency
    RuntimeBusPub = None  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover - typing helper
    from common.bus import BusPub as BusPubType
else:  # pragma: no cover - runtime fallback
    BusPubType = Any

try:  # pragma: no cover - optional dependency (pyzmq)
    from common.bus import BusPub
except Exception:  # pragma: no cover - running without bus support
    BusPub = None  # type: ignore[assignment]

from . import logging as voice_logging
from .asr import ASRConfig, Transcript, transcribe
from common.bus import BusPub, BusSub

from .capture import AudioCapture, CaptureConfig, CaptureError
from .chat import ChatConfig, ChatSession
from .kws import HotwordConfig, HotwordDetector
from .nlu import Intent, NLUConfig, NLURouter
from .common import ensure_openai_key
from .playback import PlaybackConfig, play_ding
from .tts import TTSConfig, TTSStreamResult, speak
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


@dataclass
class SpeechTask:
    text: str
    source: str
    ack: threading.Event | None = None
    accumulate: bool = False
    result: TTSStreamResult | None = None

class VoiceService:
    def __init__(self, config: dict[str, Any], *, ui_publisher: Any | None = None):
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
        ensure_openai_key(self.logger)

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
        self._ui_topic = str(service_cfg.get("ui_topic", "ui.state"))
        self._ui_pub = ui_publisher or self._create_ui_publisher(service_cfg)
        self._last_ui_state: str | None = None


        publish_ui = bool(service_cfg.get("publish_ui_state", True))
        self._ui_pub: BusPubType | None = None
        self._last_ui_state: str | None = None
        if publish_ui and RuntimeBusPub is not None:
            try:
                self._ui_pub = RuntimeBusPub()
            except Exception as exc:  # pragma: no cover - optional dependency
                self.logger.warning("service.ui_state.publisher_error", error=str(exc))
                self._ui_pub = None
                
        # Bus PUB/SUB and speech queue
        self._bus_pub: BusPub | None = None
        self._bus_sub: BusSub | None = None
        try:
            self._bus_pub = BusPub()
        except Exception as exc:
            self.logger.warning("service.bus.pub_init_failed", error=str(exc))
        try:
            self._bus_sub = BusSub("tts.speak")
        except Exception as exc:
            self.logger.warning("service.bus.sub_init_failed", error=str(exc))
            self._bus_sub = None

        self._speech_queue: queue.Queue[SpeechTask | None] = queue.Queue()
        self._speech_thread = threading.Thread(target=self._speech_worker, name="voice-speech", daemon=True)
        self._speech_thread.start()
        self._bus_thread: threading.Thread | None = None
        if self._bus_sub is not None:
            self._bus_thread = threading.Thread(target=self._tts_speak_loop, name="voice-tts-sub", daemon=True)
            self._bus_thread.start()

        self._threads: list[threading.Thread] = [self._speech_thread]
        if self._bus_thread is not None:
            self._threads.append(self._bus_thread)

        self._publish_ui_state("idle")


    # ─────────────────────────────────────────────

    def stop(self) -> None:
        self.stop_event.set()
        self._speech_queue.put(None)
        if self._bus_sub is not None:
            with contextlib.suppress(Exception):
                self._bus_sub.close()
        if self._bus_pub is not None:
            with contextlib.suppress(Exception):
                self._bus_pub.close()
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=0.5)

    def listen(self) -> None:
        self.logger.event("service.listen.start")
        self._publish_ui_state("idle")
        try:
            while not self.stop_event.is_set():
                try:
                    self._cycle()
                except Exception as exc:
                    self._publish_ui_state("idle")
                    self.logger.error("service.cycle.error", error=str(exc))
                    self._publish_ui_state("idle")
                    time.sleep(0.3)
        finally:
            self._publish_ui_state("idle")
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


    def _create_ui_publisher(self, service_cfg: dict[str, Any]) -> Any | None:
        if BusPub is None:  # pragma: no cover - optional dependency missing
            return None
        try:
            bus_cfg = service_cfg.get("ui_bus", {}) if isinstance(service_cfg, dict) else {}
            prefix = str(bus_cfg.get("prefix", "") or "")
            warmup = int(bus_cfg.get("warmup_ms", 0) or 0)
            return BusPub(prefix, warmup)
        except Exception as exc:  # pragma: no cover - optional bus
            self.logger.warning("service.ui_state.publisher_failed", error=str(exc))
            return None

    def _publish_ui_state(self, state: str) -> None:
        if self._last_ui_state == state:
            return
        if not self._ui_pub:
            self._last_ui_state = state
            return
        payload = {"state": state, "ts": time.time()}
        for attr in ("publish", "send", "pub"):
            method = getattr(self._ui_pub, attr, None)
            if callable(method):
                try:
                    method(self._ui_topic, payload)
                except Exception as exc:
                    self.logger.error(
                        "service.ui_state.publish_failed", state=state, error=str(exc)
                    )
                else:
                    self._last_ui_state = state
                return
        self.logger.warning("service.ui_state.unsupported_publisher")
        self._last_ui_state = state

    # Główna logika cyklu
    def _cycle(self, *, speak: bool = True) -> VoiceResult:
        delegated_to_speech = False
        self._publish_ui_state("hearing")
        try:
        # PTT: czekamy na ENTER bez otwartego mikrofonu → gramy ding → dopiero potem nagrywamy
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


    def _publish_ui_state(self, state: str) -> None:
        if not self._bus_pub:
            return
        try:
            self._bus_pub.publish("ui.state", {"state": state}, add_ts=True)
        except Exception as exc:
            self.logger.debug("service.bus.state_failed", state=state, error=str(exc))

    def _publish_transcript(self, transcript: Transcript) -> None:
        if not self._bus_pub:
            return
        lang = transcript.language or self._asr_cfg.language or getattr(self._asr_cfg, "lang", None) or "pl"
        payload = {"text": transcript.text, "lang": lang}
        try:
            self._bus_pub.publish("audio.transcript", payload, add_ts=True)
        except Exception as exc:
            self.logger.debug("service.bus.transcript_failed", error=str(exc))

    def _publish_assistant_speech(self, text: str) -> None:
        if not text or not self._bus_pub:
            return
        try:
            self._bus_pub.publish("assistant.speech", {"text": text}, add_ts=True)
        except Exception as exc:
            self.logger.debug("service.bus.speech_failed", error=str(exc))

    def _request_speech(self, text: str, *, source: str, accumulate: bool) -> TTSStreamResult | None:
        if not text.strip():
            return None
        task = SpeechTask(text=text, source=source, accumulate=accumulate)
        ack = threading.Event()
        task.ack = ack
        self._speech_queue.put(task)
        while not self.stop_event.is_set():
            if ack.wait(0.2):
                break
        return task.result

    def _speech_worker(self) -> None:
        while True:
            try:
                task = self._speech_queue.get(timeout=0.2)
            except queue.Empty:
                if self.stop_event.is_set():
                    break
                continue
            if task is None:
                break
            ack = task.ack
            try:
                self._publish_ui_state("speaking")
                self._publish_assistant_speech(task.text)
                result = speak(task.text, self._tts_cfg, self._play_cfg, self.logger, accumulate=task.accumulate)
                task.result = result
                if not result.ok:
                    self.logger.warning("service.speak.failed", source=task.source)
            except Exception as exc:
                self.logger.error("service.speak.error", error=str(exc), source=task.source)
                task.result = TTSStreamResult(False, None, "", 0, streamed=False)
            finally:
                self._publish_ui_state("idle")
                if ack:
                    ack.set()

    def _tts_speak_loop(self) -> None:
        sub = self._bus_sub
        if sub is None:
            return
        while not self.stop_event.is_set():
            try:
                topic, payload = sub.recv(timeout_ms=200)
            except Exception as exc:
                if self.stop_event.is_set():
                    break
                self.logger.debug("service.bus.sub_error", error=str(exc))
                time.sleep(0.2)
                continue
            if not payload:
                continue
            text = payload.get("text") if isinstance(payload, dict) else None
            if not isinstance(text, str) or not text.strip():
                continue
            self._speech_queue.put(SpeechTask(text=text.strip(), source="bus", accumulate=False))
    # Główna logika cyklu
    def _cycle(self, *, speak: bool = True) -> VoiceResult:
        waiting_without_capture = self._hotword_engine == "ptt" or (not self._hotword_enabled)
        if waiting_without_capture:
            if not self._wait_hotword_without_capture():
                raise RuntimeError("Hotword/PTT timeout")

            if speak:
                self._play_start_ding()
            self._publish_ui_state("hearing")
            audio = self._record_with_vad()
        else:
            with AudioCapture(self._capture_cfg, self.logger) as capture:
                if not self._hotword.wait(capture):
                    raise RuntimeError("Hotword timeout")

                if speak:
                    self._play_start_ding()
                # po ding zbieramy właściwe wypowiedzi
                self._publish_ui_state("hearing")
                audio = collect(capture.frames(), self._vad, self._max_len)

        if not audio:
            self._publish_ui_state("idle")
            raise RuntimeError("No audio captured")

        if speak:
            self._play_start_ding()
        self._publish_ui_state("hearing")
        speech_task_enqueued = False
        speech_result: TTSStreamResult | None = None
        try:
            audio = self._record_with_vad()


            if not audio:
                raise RuntimeError("No audio captured")


        self._publish_ui_state("thinking")
        start = time.time()
        transcript = transcribe(audio, self._capture_cfg.sample_rate, self._asr_cfg, self.logger)
        # widoczność transkryptu
        self.logger.event("service.asr.transcript", text=transcript.text)

        intent = self._nlu.route(transcript.text)
        reply = self._handle_intent(intent)
        reply_text = reply.strip()

        audio_out: bytes | None = None
        sample_rate = 0
        fmt = ""
        queued_tts = False
        if reply_text:
            audio_out, sample_rate, fmt = synthesize(reply_text, self._tts_cfg, self.logger)
            if speak:
                self._publish_ui_state("speaking")
                queued_tts = True
                # nieblokujące odtwarzanie
                play_bytes(audio_out, fmt, self._play_cfg, self.logger, blocking=False)
        if not queued_tts:
            self._publish_ui_state("idle")

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

            if self._save_audio:
                self._save_pcm(audio)


            self._publish_ui_state("thinking")

            start = time.time()
            transcript = transcribe(audio, self._capture_cfg.sample_rate, self._asr_cfg, self.logger)
            # widoczność transkryptu
            self.logger.event("service.asr.transcript", text=transcript.text)

            intent = self._nlu.route(transcript.text)
            reply = self._handle_intent(intent)
            stripped_reply = reply.strip()

            audio_out: bytes | None = None
            sample_rate = 0
            fmt = ""

            if stripped_reply:
                audio_out, sample_rate, fmt = synthesize(reply, self._tts_cfg, self.logger)
                if speak and audio_out:
                    self._publish_ui_state("speaking")
                    # nieblokujące odtwarzanie
                    play_bytes(audio_out, fmt, self._play_cfg, self.logger, blocking=False)
                    delegated_to_speech = True
            else:
                self.logger.event("service.reply.empty")

            latency = time.time() - start
            self.logger.event("service.cycle.done", latency=latency, intent=intent.kind)

            start = time.time()
            transcript = transcribe(audio, self._capture_cfg.sample_rate, self._asr_cfg, self.logger)
            self.logger.event("service.asr.transcript", text=transcript.text)
            self._publish_transcript(transcript)

            intent = self._nlu.route(transcript.text)
            reply = self._handle_intent(intent)

            processing_latency = time.time() - start

            if speak and reply.strip():
                speech_task_enqueued = True
                speech_result = self._request_speech(reply, source="chat", accumulate=True)
            elif speak:
                self.logger.debug("service.tts.skip_empty")

            total_latency = time.time() - start
            self.logger.event(
                "service.cycle.done",
                latency=total_latency,
                processing=processing_latency,
                intent=intent.kind,
            )

            audio_bytes = speech_result.audio if speech_result and speech_result.audio else None
            audio_format = speech_result.audio_format if speech_result else ""
            sample_rate = speech_result.sample_rate if speech_result else 0


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
            if not delegated_to_speech:
                latency_s=total_latency,
                audio=audio_bytes,
                audio_format=audio_format,
                sample_rate=sample_rate,
            )
        finally:
            if not speech_task_enqueued:

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
        """Zbierz wypowiedź VAD-em z fallbackiem do arecord."""
        audio = b""
        try:
            with AudioCapture(self._capture_cfg, self.logger) as capture:
                audio = collect(capture.frames(), self._vad, self._max_len)
        except CaptureError as exc:
            self.logger.warning("service.capture.error", error=str(exc))
        except Exception as exc:
            self.logger.warning("service.capture.unexpected", error=str(exc))
        if not audio:
            audio = self._record_with_arecord()
        return audio


    def _record_with_arecord(self) -> bytes:
        cfg = self._capture_cfg
        device = cfg.device or "plughw:1,0"
        buffer_seconds = float(getattr(cfg, "buffer_seconds", 0) or 0.0)
        duration = max(self._max_len / 1000.0, 1.0) + buffer_seconds + 0.5
        cmd = [
            "arecord",
            "-q",
            "-t",
            "raw",
            "-f",
            "S16_LE",
            "-c",
            str(max(1, int(cfg.channels))),
            "-r",
            str(cfg.sample_rate),
            "-D",
            device,
            "-d",
            f"{duration:.2f}",
        ]
        buffer_us = int(max(0.0, buffer_seconds) * 1_000_000)
        if buffer_us > 0:
            cmd += ["--buffer-time", str(buffer_us)]
        self.logger.debug("service.capture.fallback.start", command=" ".join(cmd))
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        except FileNotFoundError:
            self.logger.error("service.capture.arecord_missing")
            return b""
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", "ignore").strip()
            self.logger.error(
                "service.capture.arecord_failed",
                returncode=proc.returncode,
                stderr=stderr,
            )
            return b""
        raw = proc.stdout or b""
        if not raw:
            self.logger.warning("service.capture.arecord_empty")
            return b""
        frames = self._frames_from_pcm(raw, cfg.frame_bytes)
        trimmed = collect(frames, self._vad, self._max_len)
        if trimmed:
            self.logger.event("service.capture.fallback.success", backend="arecord", bytes=len(trimmed))
            return trimmed
        self.logger.warning("service.capture.fallback.no_vad")
        return raw

    def _frames_from_pcm(self, data: bytes, frame_size: int):
        for offset in range(0, len(data), frame_size):
            chunk = data[offset : offset + frame_size]
            if len(chunk) < frame_size:
                break
            yield chunk
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

# ─────────────────────────────────────────────

def setup_signals(service: VoiceService) -> None:
    def handler(signum, frame):  # pragma: no cover - signal handler
        service.logger.event("service.signal", signum=signum)
        service.stop()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
