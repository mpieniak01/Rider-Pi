# apps/voice/service.py
"""Voice assistant service loop (clean, consolidated, hardened)."""

from __future__ import annotations

import contextlib
import math
import queue
import signal
import subprocess
import threading
import time
import wave
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ──────────────────────────────────────────────────────────────────────────────
# Bus (opcjonalny w runtime)
try:  # pragma: no cover - optional dependency
    from common.bus import BusPub, BusSub  # type: ignore
except Exception:  # pragma: no cover
    BusPub = None  # type: ignore[assignment]
    BusSub = None  # type: ignore[assignment]

# Lokalny logger (NIE koliduje ze stdlib logging)
from . import voice_logging as vlog
from .asr import ASRConfig, Transcript, transcribe
from .capture import AudioCapture, CaptureConfig, CaptureError
from .chat import ChatConfig, ChatSession
from .common import ensure_openai_key
from .kws import HotwordConfig, HotwordDetector
from .nlu import Intent, NLUConfig, NLURouter
from .playback import PlaybackConfig, play_ding
from .tts import TTSConfig, TTSStreamResult, speak
from .vad import WebRtcActivity, collect

# ──────────────────────────────────────────────────────────────────────────────


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
    accumulate: bool = False
    ack: threading.Event | None = None
    result: TTSStreamResult | None = None


class VoiceService:
    def __init__(self, config: dict[str, Any], ui_publisher: Any | None = None) -> None:
        self.config = config
        self.logger = vlog.get_logger("voice.service")
        self.stop_event = threading.Event()

        # Bus (pozwól testom wstrzyknąć fałszywego publishra)
        self._bus_pub = ui_publisher if ui_publisher is not None else (BusPub() if BusPub else None)
        self._bus_sub = BusSub("tts.speak") if BusSub else None

        # Sesje i konfiguracje
        self._chat = ChatSession(ChatConfig(**config["chat"]))
        self._nlu = NLURouter(NLUConfig(**config["nlu"]))

        self._capture_cfg = CaptureConfig(**config["capture"])
        self._asr_cfg = ASRConfig(**config["asr"])

        allowed_tts = {"backend", "voice", "model", "format", "piper_model", "piper_config"}
        tts_kwargs = {k: v for k, v in config["tts"].items() if k in allowed_tts}
        self._tts_cfg = TTSConfig(**tts_kwargs)

        self._play_cfg = PlaybackConfig(**config["playback"])
        ensure_openai_key(self.logger)

        # Hotword / PTT
        hotword_cfg = config.get("hotword", {})
        self._hotword = HotwordDetector(HotwordConfig(**hotword_cfg))
        self._hotword_engine = (hotword_cfg.get("engine") or "ptt").lower()
        self._hotword_enabled = bool(hotword_cfg.get("enabled", False))

        # VAD
        vad_cfg = config.get("vad", {})
        # Wymuś >= 1000 ms podtrzymania po mowie – nie ucinamy końcówek
        requested_tail = int(vad_cfg.get("tail_ms", 800))
        enforced_tail = max(1000, requested_tail)
        self._vad = WebRtcActivity(
            sample_rate=self._capture_cfg.sample_rate,
            mode=int(vad_cfg.get("mode", 3)),
            frame_ms=int(vad_cfg.get("frame_ms", self._capture_cfg.frame_ms)),
            tail_ms=enforced_tail,
            energy_gate=float(vad_cfg.get("energy_gate_dbfs", -30.0)),
        )
        self._max_len = int(vad_cfg.get("max_len_ms", 12000))

        # Service
        service_cfg = config.get("service", {})
        self._save_audio = bool(service_cfg.get("save_audio", False))
        self._recordings_dir = Path(service_cfg.get("recordings_dir", "/tmp/voice-recs"))

        # Timingi stabilizujące nagrania
        self._beep_pause_ms = int(service_cfg.get("beep_pause_ms", 250))  # pauza logiczna po ding (mute)
        self._mic_open_delay_ms = int(service_cfg.get("mic_open_delay_ms", 100))  # stabilizacja ALSA po otwarciu
        self._post_tts_mute_ms = int(service_cfg.get("post_tts_mute_ms", 300))  # po TTS wstrzymaj zbieranie

        # Minima zbierania: 1) oczekiwanie na start mowy, 2) całkowity czas klipu
        self._pre_speech_wait_ms = int(service_cfg.get("pre_speech_wait_ms", 1000))
        self._min_capture_ms = int(service_cfg.get("min_capture_ms", 1000))

        # Okno wyciszenia po ding/TTS
        self._mute_until_ts: float = 0.0

        # UI state cache
        self._last_ui_state: str | None = None

        # Kolejka mówienia
        self._speech_queue: queue.Queue[SpeechTask | None] = queue.Queue()
        self._speech_thread = threading.Thread(target=self._speech_worker, name="voice-speech", daemon=True)
        self._speech_thread.start()

        # Subskrybent tts.speak
        self._bus_thread: threading.Thread | None = None
        if self._bus_sub is not None:
            self._bus_thread = threading.Thread(target=self._tts_speak_loop, name="voice-tts-sub", daemon=True)
            self._bus_thread.start()

        self._threads = [t for t in (self._speech_thread, self._bus_thread) if t is not None]

        # DING cooldown (anty-pętla)
        self._last_ding_ts: float = 0.0

        # Startowy stan
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
        for t in self._threads:
            if t.is_alive():
                t.join(timeout=0.5)

    # ─────────────────────────────────────────────
    # Publikacje na busie

    def _publish_ui_state(self, state: str) -> None:
        if state == self._last_ui_state:
            return
        self._last_ui_state = state
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

    # ─────────────────────────────────────────────
    # Kolejka mówienia

    def _request_speech(self, text: str, *, source: str, accumulate: bool) -> TTSStreamResult | None:
        if not text.strip():
            return None
        task = SpeechTask(text=text.strip(), source=source, accumulate=accumulate)
        task.ack = threading.Event()
        self._speech_queue.put(task)
        while not self.stop_event.is_set():
            if task.ack.wait(0.2):
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

            try:
                self._publish_ui_state("speaking")
                self._publish_assistant_speech(task.text)

                # Zablokuj wejście na czas TTS (okno mute)
                tts_block_s = (self._post_tts_mute_ms / 1000.0) + 0.2
                self._mute_until_ts = max(self._mute_until_ts, time.time() + tts_block_s)

                result = speak(
                    task.text,
                    self._tts_cfg,
                    self._play_cfg,
                    self.logger,
                    accumulate=task.accumulate,
                )
                task.result = result
                if not result.ok:
                    self.logger.warning("service.speak.failed", source=task.source)
            except Exception as exc:
                self.logger.error("service.speak.error", error=str(exc), source=task.source)
                task.result = TTSStreamResult(False, None, "", 0, streamed=False)
            finally:
                # Dociągnij okno mute po mowie (anty-echo)
                self._mute_until_ts = max(self._mute_until_ts, time.time() + (self._post_tts_mute_ms / 1000.0))
                self._publish_ui_state("idle")
                if task.ack:
                    task.ack.set()

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

    # ─────────────────────────────────────────────

    def listen(self) -> None:
        self.logger.event("service.listen.start")
        self._publish_ui_state("idle")
        try:
            while not self.stop_event.is_set():
                try:
                    self._cycle(speak=True)
                except Exception as exc:
                    # po błędzie zawsze wracaj do idle
                    self._publish_ui_state("idle")
                    self.logger.error("service.cycle.error", error=str(exc))
                    time.sleep(0.3)
        finally:
            self._publish_ui_state("idle")
            self.logger.event("service.listen.stop")

    def once(self, *, speak: bool = True) -> VoiceResult | None:
        try:
            return self._cycle(speak=speak)
        except Exception as exc:
            self._publish_ui_state("idle")
            self.logger.error("service.once.error", error=str(exc))
            return None

    # ─────────────────────────────────────────────
    # Główna tura

    def _cycle(self, *, speak: bool = True) -> VoiceResult:
        # Reset VAD state to ensure clean detection for this recording cycle
        self._vad.reset()
<<<<<<< HEAD

=======
        
>>>>>>> 6dc1d58 (Fix VAD state persistence causing voice recording loop failures)
        # Wejście – słuchamy
        self._publish_ui_state("hearing")

        # Jeśli trwa jeszcze okno wyciszenia po ding/TTS – odczekaj
        now = time.time()
        if now < self._mute_until_ts:
            time.sleep(self._mute_until_ts - now)

        waiting_without_capture = self._hotword_engine == "ptt" or (not self._hotword_enabled)

        if waiting_without_capture:
            if not self._wait_hotword_without_capture():
                self._publish_ui_state("idle")
                raise RuntimeError("Hotword/PTT timeout")
            if speak and self._should_ding():
                play_ding(self._play_cfg, self.logger)
                self._last_ding_ts = time.time()
                # po ding ustaw okno mute (nie nagrywaj dźwięku beep)
                self._mute_until_ts = max(self._mute_until_ts, time.time() + (self._beep_pause_ms / 1000.0))
            audio = self._record_with_vad()
        else:
            with AudioCapture(self._capture_cfg, self.logger) as capture:
                if not self._hotword.wait(capture):
                    self._publish_ui_state("idle")
                    raise RuntimeError("Hotword timeout")
                if speak and self._should_ding():
                    play_ding(self._play_cfg, self.logger)
                    self._last_ding_ts = time.time()
                    self._mute_until_ts = max(self._mute_until_ts, time.time() + (self._beep_pause_ms / 1000.0))
                # małe opóźnienie po otwarciu device
                if self._mic_open_delay_ms > 0:
                    time.sleep(self._mic_open_delay_ms / 1000.0)
                # zbieramy
                audio = collect(capture.frames(), self._vad, self._max_len)

        if not audio:
            self._publish_ui_state("idle")
            raise RuntimeError("No audio captured")

        if self._save_audio:
            self._save_pcm(audio)

        # Przetwarzanie
        self._publish_ui_state("thinking")
        start = time.time()

        transcript = transcribe(audio, self._capture_cfg.sample_rate, self._asr_cfg, self.logger)
        self.logger.event("service.asr.transcript", text=transcript.text)
        self._publish_transcript(transcript)

        intent = self._nlu.route(transcript.text)
        reply = self._handle_intent(intent)
        reply_text = reply.strip()

        # Mówienie (odtworzenie odpowiedzi – TTS)
        speech_task_enqueued = False
        speech_result: TTSStreamResult | None = None

        if speak and reply_text:
            speech_task_enqueued = True
            speech_result = self._request_speech(reply_text, source="chat", accumulate=True)

        total_latency = time.time() - start
        self.logger.event(
            "service.cycle.done",
            latency=total_latency,
            intent=intent.kind,
        )

        # Wynik do ewentualnego UI/API
        audio_bytes = speech_result.audio if (speech_result and speech_result.audio) else None
        audio_format = speech_result.audio_format if speech_result else ""
        sample_rate = speech_result.sample_rate if speech_result else 0

        # Jeśli nie mówimy – przywróć idle tu; jeżeli mówimy, worker zrobi to sam.
        if not speech_task_enqueued:
            self._publish_ui_state("idle")

        # krótki cooldown po mowie/PTT – nie łap echa ani „zależnych” ENTER-ów
        if self._hotword_engine == "ptt":
            if self._post_tts_mute_ms > 0:
                time.sleep(self._post_tts_mute_ms / 1000.0)
            time.sleep(0.15)
            try:
                import sys
                import termios  # late import; brak zależności pod systemd

                termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
            except Exception:
                pass

        return VoiceResult(
            transcript=transcript,
            intent=intent,
            reply=reply,
            latency_s=total_latency,
            audio=audio_bytes,
            audio_format=audio_format,
            sample_rate=sample_rate,
        )

    # ─────────────────────────────────────────────
    # Pomocnicze

    def _should_ding(self) -> bool:
        # PlaybackConfig.ding to dict -> sprawdzaj .get("enabled")
        ding_cfg = getattr(self._play_cfg, "ding", None)
        if isinstance(ding_cfg, dict):
            ok = bool(ding_cfg.get("enabled", False))
        else:
            ok = bool(getattr(ding_cfg, "enabled", False))
        # cooldown anty-pętla (≥1.0 s)
        if ok and (time.time() - self._last_ding_ts) < 1.0:
            return False
        return ok

    def _wait_hotword_without_capture(self) -> bool:
        """PTT/keyboard: czekaj na wyzwolenie bez otwartego mikrofonu."""
        if self._hotword_engine == "ptt":
            try:
                return bool(self._hotword.wait_ptt(timeout=60.0))  # type: ignore[attr-defined]
            except AttributeError:
                try:
                    return bool(self._hotword.wait(None))
                except TypeError:

                    class _NullCap:
                        def frames(self) -> Iterable[bytes]:  # pragma: no cover
                            if False:
                                yield b""

                    return bool(self._hotword.wait(_NullCap()))
        try:
            return bool(self._hotword.wait(None))
        except TypeError:

            class _NullCap:
                def frames(self) -> Iterable[bytes]:  # pragma: no cover
                    if False:
                        yield b""

            return bool(self._hotword.wait(_NullCap()))

    def _record_with_vad(self) -> bytes:
        """
        Kolejność:
        1) Poczekaj aż wygaśnie mute po beep/TTS (żeby nie nagrać „ding”).
        2) Otwórz mikrofon i ustabilizuj ALSA.
        3) Zbierz *co najmniej* pre_speech_wait_ms ramek (czekanie na głos),
           dopiero wtedy pozwól VAD skracać nagranie.
        4) VAD ma tail >= 1000 ms, więc trzyma ~1 s po zakończeniu mowy.
        """
        # 1) czekamy do końca mute
        now = time.time()
        if now < self._mute_until_ts:
            time.sleep(self._mute_until_ts - now)

        # --- NOWE: zresetuj stan detektora przed każdą turą (jeśli posiada taką metodę)
        try:
            reset = getattr(self._vad, "reset", None)
            if callable(reset):
                reset()
        except Exception:
            pass

        audio = b""
        try:
            with AudioCapture(self._capture_cfg, self.logger) as capture:
                # 2) stabilizacja toru po otwarciu (WM8960 bywa „leniwy” zaraz po TTS)
                if self._mic_open_delay_ms > 0:
                    time.sleep(max(self._mic_open_delay_ms, 200) / 1000.0)

                frames_iter = capture.frames()

                # 3) pre-roll: wymagamy co najmniej pre_speech_wait_ms zanim pozwolimy VAD zakończyć
                pre_frames_needed = max(1, int(math.ceil(self._pre_speech_wait_ms / self._capture_cfg.frame_ms)))
                pre_buf: list[bytes] = []
                for _ in range(pre_frames_needed):
                    try:
                        pre_buf.append(next(frames_iter))
                    except StopIteration:
                        break

                # jeśli niewiele zebraliśmy (np. wolny start), dozbieraj do 0.6 s
                if len(pre_buf) < pre_frames_needed // 4:
                    t0 = time.time()
                    while len(pre_buf) < pre_frames_needed and (time.time() - t0) < 0.6:
                        try:
                            pre_buf.append(next(frames_iter))
                        except StopIteration:
                            break

                def _chained():
                    for f in pre_buf:
                        if f:
                            yield f
                    for f in frames_iter:
                        yield f

                audio = collect(_chained(), self._vad, self._max_len)

        except CaptureError as exc:
            self.logger.warning("service.capture.error", error=str(exc))
        except Exception as exc:
            self.logger.warning("service.capture.unexpected", error=str(exc))

        # Minimalna długość całego klipu
        min_ms = max(200, self._min_capture_ms)
        bytes_per_sample = 2  # 16-bit
        channels = max(1, int(getattr(self._capture_cfg, "channels", 1)))
        expected_min = int(self._capture_cfg.sample_rate * (min_ms / 1000.0)) * bytes_per_sample * channels

        # brak czegokolwiek → pewny fallback (arecord 2–4 s)
        if not audio:
            self.logger.debug("service.capture.empty_retry_arecord")
            return self._record_with_arecord()

        # za krótkie → krótki dogryw (~0.8 s) i ponowna próba na zebranym buforze
        if len(audio) < expected_min:
            self.logger.debug("service.capture.retry_short_clip", bytes=len(audio), threshold=expected_min)
            try:
                with AudioCapture(self._capture_cfg, self.logger) as capture:
                    if self._mic_open_delay_ms > 0:
                        time.sleep(max(self._mic_open_delay_ms, 200) / 1000.0)
                    t0 = time.time()
                    chunks: list[bytes] = []
                    for f in capture.frames():
                        chunks.append(f)
                        if (time.time() - t0) >= 0.8:
                            break
                    audio2 = collect(iter(chunks), self._vad, self._max_len)
                    if audio2 and len(audio2) > len(audio):
                        audio = audio2
            except Exception as exc:
                self.logger.debug("service.capture.retry_error", error=str(exc))

            if len(audio) < expected_min:
                self.logger.debug("service.capture.fast_fail.too_short", bytes=len(audio), threshold=expected_min)
                return b""

        # dodatkowa diagnostyka (rozmiar końcowy)
        try:
            self.logger.debug(
                "service.capture.final_size",
                bytes=len(audio),
                min_required=expected_min,
                pre_wait_ms=self._pre_speech_wait_ms,
                tail_ms=getattr(self._vad, "tail_ms", 0),
            )
        except Exception:
            pass

        return audio

    def _record_with_arecord(self) -> bytes:
        cfg = self._capture_cfg
        device = cfg.device or "plughw:1,0"
        buffer_seconds = float(getattr(cfg, "buffer_seconds", 0) or 0.0)

        # arecord -d wymaga całych sekund → ogranicz do max 4 s, min 2 s
        duration_float = max(self._max_len / 1000.0, 1.0) + buffer_seconds + 0.5
        duration_s = int(math.ceil(duration_float))
        duration_s = max(2, min(4, duration_s))

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
            str(duration_s),
        ]

        buffer_us = int(max(0.0, buffer_seconds) * 1_000_000)
        if buffer_us > 0:
            cmd += ["--buffer-time", str(buffer_us)]

        self.logger.debug("service.capture.fallback.start", command=" ".join(cmd))
        try:
            proc = subprocess.run(cmd, capture_output=True, check=False)
        except FileNotFoundError:
            self.logger.error("service.capture.arecord_missing")
            return b""
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", "ignore").strip()
            self.logger.error("service.capture.arecord_failed", returncode=proc.returncode, stderr=stderr)
            return b""
        raw = proc.stdout or b""
        if not raw:
            self.logger.warning("service.capture.arecord_empty")
            return b""

        # pofragmentuj „raw” na ramki i spróbuj VAD-ować
        frames = self._frames_from_pcm(raw, self._capture_cfg.frame_bytes)
        trimmed = collect(frames, self._vad, self._max_len)

        # Minimalna długość
        min_ms = max(200, self._min_capture_ms)
        bytes_per_sample = 2
        channels = max(1, int(getattr(self._capture_cfg, "channels", 1)))
        expected_min = int(self._capture_cfg.sample_rate * (min_ms / 1000.0)) * bytes_per_sample * channels

        if trimmed:
            if len(trimmed) >= expected_min:
                self.logger.event("service.capture.fallback.success", backend="arecord", bytes=len(trimmed))
                return trimmed
            # przycięte za krótkie → spróbuj oddać raw jeśli ma sensowny rozmiar
            if len(raw) >= max(1, expected_min // 2):
                self.logger.warning(
                    "service.capture.fallback.trimmed_too_short_using_raw",
                    bytes_trimmed=len(trimmed),
                    bytes_raw=len(raw),
                )
                return raw
            self.logger.warning(
                "service.capture.fallback.trimmed_too_short",
                bytes_trimmed=len(trimmed),
                bytes_required=expected_min,
            )
            return b""

        # gdy VAD nic nie wykroił – oddaj raw jeżeli sensowny
        if len(raw) >= max(1, expected_min // 2):
            self.logger.warning("service.capture.fallback.no_vad_using_raw", bytes=len(raw))
            return raw

        self.logger.warning("service.capture.fallback.no_vad")
        return b""

    def _frames_from_pcm(self, data: bytes, frame_size: int):
        for off in range(0, len(data), frame_size):
            chunk = data[off : off + frame_size]
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
        ts = time.time()
        filename = f"capture_{int(ts)}_{int((ts % 1) * 1000):03d}.wav"
        path = self._recordings_dir / filename
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(max(1, int(getattr(self._capture_cfg, "channels", 1))))
            wf.setsampwidth(2)
            wf.setframerate(self._capture_cfg.sample_rate)
            wf.writeframes(audio)
        self.logger.event("service.audio.saved", path=str(path))


# ─────────────────────────────────────────────


def setup_signals(service: VoiceService) -> None:
    def handler(signum, frame):  # pragma: no cover
        service.logger.event("service.signal", signum=signum)
        service.stop()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
