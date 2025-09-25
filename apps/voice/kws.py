"""Keyword spotting and hotword helpers."""

from __future__ import annotations

import contextlib
import os
import select
import sys
import termios
import threading
import time
import tty
from dataclasses import dataclass
from typing import Any, Callable

from . import voice_logging as voice_logging

# ──────────────────────────────────────────────────────────────────────────────
# Opcjonalne backendy
try:  # pragma: no cover - optional dependency
    from libnyumaya import AudioRecognition, FeatureExtractor  # type: ignore

    _HAS_NYUMAYA = True
except Exception:  # pragma: no cover
    AudioRecognition = None
    FeatureExtractor = None
    _HAS_NYUMAYA = False

try:  # pragma: no cover - optional dependency
    import pvporcupine  # type: ignore

    _HAS_PORCUPINE = True
except Exception:  # pragma: no cover
    pvporcupine = None
    _HAS_PORCUPINE = False


# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class HotwordConfig:
    enabled: bool
    engine: str  # "off" | "ptt" | "nyumaya" | "porcupine"
    model: str | None = None  # ścieżka do modelu (nyumaya/porcupine)
    library: str | None = None  # ścieżka do lib (nyumaya)
    sensitivity: float = 0.6  # 0..1
    auto_gain: float = 1.0  # nyumaya
    threshold: float = 0.6  # rezerwowe


# ──────────────────────────────────────────────────────────────────────────────


class HotwordDetector:
    """
    Obsługa PTT oraz hotwordów (Nyumaya / Porcupine).
    Działa w trybie blokującym: `wait(...) -> bool`.
    """

    def __init__(self, config: HotwordConfig, logger: voice_logging.VoiceLogger | None = None):
        self.config = self._sanitize_config(config)
        self.logger = logger or voice_logging.get_logger("voice.hotword")
        self._mode = (self.config.engine or "off").lower()
        if not self.config.enabled:
            self._mode = "off"

        self._stop = threading.Event()
        self._nyumaya: tuple[Any, Any, int, int] | None = None  # (extractor, detector, keyword_id, frame_size)
        self._porcupine: Any | None = None

        # Inicjalizacja backendów
        if self._mode == "nyumaya":
            self._init_nyumaya()
        elif self._mode == "porcupine":
            self._init_porcupine()

    # ────────────────────────────────────────── init & teardown

    def _sanitize_config(self, cfg: HotwordConfig) -> HotwordConfig:
        # przytnij zakresy i normalizuj
        s = 0.0 if cfg.sensitivity < 0.0 else (1.0 if cfg.sensitivity > 1.0 else cfg.sensitivity)
        thr = 0.0 if cfg.threshold < 0.0 else (1.0 if cfg.threshold > 1.0 else cfg.threshold)
        return HotwordConfig(
            enabled=cfg.enabled,
            engine=(cfg.engine or "off").lower(),
            model=cfg.model,
            library=cfg.library,
            sensitivity=s,
            auto_gain=cfg.auto_gain,
            threshold=thr,
        )

    def _init_nyumaya(self) -> None:
        if not _HAS_NYUMAYA:
            self.logger.warning("hotword.backend_unavailable", engine="nyumaya")
            self._mode = "off"
            return
        if not self.config.model:
            self.logger.warning("hotword.nyumaya_no_model")
            self._mode = "off"
            return
        library = self.config.library or os.environ.get("HOTWORD_LIB_PATH")
        try:
            extractor = FeatureExtractor(library)
            detector = AudioRecognition(library)
            keyword_id = detector.addModel(self.config.model, self.config.sensitivity)
            frame_size = detector.getInputDataSize()
            self._nyumaya = (extractor, detector, keyword_id, frame_size)
            self.logger.event("hotword.nyumaya", model=self.config.model, frame_size=frame_size)
        except Exception as exc:  # pragma: no cover
            self.logger.error("hotword.nyumaya_failed", error=str(exc))
            self._mode = "off"

    def _init_porcupine(self) -> None:
        if not _HAS_PORCUPINE:
            self.logger.warning("hotword.backend_unavailable", engine="porcupine")
            self._mode = "off"
            return
        if not self.config.model:
            self.logger.warning("hotword.porcupine_no_model")
            self._mode = "off"
            return
        try:
            self._porcupine = pvporcupine.create(
                keyword_paths=[self.config.model], sensitivities=[self.config.sensitivity]
            )
            self.logger.event("hotword.porcupine", model=self.config.model)
        except Exception as exc:  # pragma: no cover
            self.logger.error("hotword.porcupine_failed", error=str(exc))
            self._mode = "off"

    def stop(self) -> None:
        """Zatrzymaj oczekiwanie i zwolnij zasoby backendów."""
        self._stop.set()
        if self._porcupine:
            with contextlib.suppress(Exception):  # type: ignore[name-defined]
                self._porcupine.delete()
            self._porcupine = None
        # Nyumaya nie wymaga jawnego .delete(); pozwól zebrać GC.

    # ────────────────────────────────────────── PTT (push-to-talk)

    def wait_ptt(
        self,
        *,
        prompt: str = "[voice] Press ENTER to speak…",
        timeout: float | None = None,
    ) -> bool:
        """
        Czekaj na ENTER na lokalnym TTY.

        - czyści bufor wejściowy przed i po wciśnięciu (żeby kolejne cykle się nie „zapętlały”),
        - non-canonical + select() → brak blokady,
        - debounce ~120 ms,
        - honoruje self._stop oraz timeout.
        """
        # Jeśli stdin nie jest TTY (np. systemd), nie auto-wyzwalaj; czekaj do timeout.
        if not sys.stdin or not sys.stdin.isatty():
            start = time.time()
            self.logger.debug("hotword.ptt.no_tty")
            while not self._stop.is_set():
                if timeout is not None and (time.time() - start) > timeout:
                    return False
                time.sleep(0.05)
            return False

        fd = sys.stdin.fileno()

        # wyczyść ewentualne pozostałości po poprzednim cyklu
        with contextlib.suppress(Exception):
            termios.tcflush(fd, termios.TCIFLUSH)

        try:
            sys.stdout.write(prompt + "\n")
            sys.stdout.flush()
        except Exception:
            pass

        old_attrs = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)  # non-canonical, bez echa
            start = time.time()
            while not self._stop.is_set():
                if timeout is not None and (time.time() - start) > timeout:
                    return False
                r, _, _ = select.select([sys.stdin], [], [], 0.1)
                if not r:
                    continue
                ch = sys.stdin.read(1)
                if ch in ("\n", "\r"):
                    # debounce + flush reszty
                    time.sleep(0.12)
                    with contextlib.suppress(Exception):
                        termios.tcflush(fd, termios.TCIFLUSH)
                    self.logger.event("hotword.trigger", engine="ptt")
                    return True
                # inne znaki ignorujemy
        finally:
            with contextlib.suppress(Exception):
                termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)

    # ────────────────────────────────────────── API ogólne

    def wait(self, capture: Any, timeout: float | None = None) -> bool:
        """Blokuj do wykrycia hotwordu/PTT lub do upłynięcia timeout."""
        start = time.time()

        if self._mode in {"off", "none"}:
            return True  # brak hotwordu → zawsze „gotowe”

        if self._mode == "ptt":
            return self.wait_ptt(timeout=timeout)

        if self._mode == "nyumaya" and self._nyumaya:
            return self._wait_nyumaya(capture, timeout, start)

        if self._mode == "porcupine" and self._porcupine:
            return self._wait_porcupine(capture, timeout, start)

        # awaryjnie: nie blokuj
        return True

    # ────────────────────────────────────────── Backend: Nyumaya

    def _wait_nyumaya(self, capture: Any, timeout: float | None, start: float) -> bool:
        extractor, detector, keyword_id, frame_size = self._nyumaya
        read = _make_reader(capture)

        # Nyumaya oczekuje ramki po 16-bit (2 bajty na próbkę)
        bytes_per_frame = frame_size * 2

        while not self._stop.is_set():
            if timeout and time.time() - start > timeout:
                return False
            data = read(bytes_per_frame)
            if not data or len(data) < bytes_per_frame:
                time.sleep(0.01)
                continue
            try:
                features = extractor.signalToMel(data, self.config.auto_gain)
                prediction = detector.runDetection(features)
                if prediction == keyword_id:
                    self.logger.event("hotword.trigger", engine="nyumaya")
                    return True
            except Exception as exc:  # pragma: no cover
                self.logger.debug("hotword.nyumaya.process_error", error=str(exc))
                time.sleep(0.01)
        return False

    # ────────────────────────────────────────── Backend: Porcupine

    def _wait_porcupine(self, capture: Any, timeout: float | None, start: float) -> bool:
        porcupine = self._porcupine
        read = _make_reader(capture)
        frame_length = porcupine.frame_length
        need_bytes = frame_length * 2  # 16-bit PCM

        # prosty bufor na niedomknięte odczyty
        pending = bytearray()

        while not self._stop.is_set():
            if timeout and time.time() - start > timeout:
                return False

            # dobuduj brakujące bajty do pełnej ramki
            while len(pending) < need_bytes and not self._stop.is_set():
                chunk = read(need_bytes - len(pending))
                if not chunk:
                    time.sleep(0.01)
                    break
                pending.extend(chunk)

            if len(pending) < need_bytes:
                continue

            frame = bytes(pending[:need_bytes])
            del pending[:need_bytes]

            # konwersja LE 16-bit -> int
            pcm = [int.from_bytes(frame[i : i + 2], "little", signed=True) for i in range(0, need_bytes, 2)]
            try:
                result = porcupine.process(pcm)
                if result >= 0:
                    self.logger.event("hotword.trigger", engine="porcupine")
                    return True
            except Exception as exc:  # pragma: no cover
                self.logger.debug("hotword.porcupine.process_error", error=str(exc))
                time.sleep(0.01)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Narzędzia pomocnicze
# ──────────────────────────────────────────────────────────────────────────────


def _make_reader(capture: Any) -> Callable[[int], bytes]:
    """
    Zwraca funkcję read(n)->bytes dla różnych typów „capture”:
    - jeśli obiekt ma .read(n): użyj go,
    - jeśli ma .frames(): zlepiaj kolejne ramki aż do n bajtów,
    - w przeciwnym razie: no-op (zwracaj b"").
    """
    if hasattr(capture, "read") and callable(capture.read):
        return lambda n: _safe_read(capture.read, n)

    if hasattr(capture, "frames") and callable(capture.frames):
        frames_iter = iter(capture.frames())

        def _read_from_frames(n: int) -> bytes:
            out = bytearray()
            try:
                while len(out) < n:
                    chunk = next(frames_iter, None)
                    if not chunk:
                        break
                    out.extend(chunk)
            except Exception:
                # zachowaj ciszę przy błędach iteratora
                return bytes(out)
            return bytes(out)

        return _read_from_frames

    # fallback
    return lambda n: b""


def _safe_read(fn: Callable[[int], bytes], n: int) -> bytes:
    try:
        return fn(n)
    except Exception:
        return b""


def disabled() -> HotwordDetector:
    return HotwordDetector(HotwordConfig(enabled=False, engine="off"))
