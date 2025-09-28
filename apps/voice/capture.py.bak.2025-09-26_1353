# apps/voice/capture.py
from __future__ import annotations

import contextlib
import shlex
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

from . import voice_logging as voice_logging


class CaptureError(RuntimeError):
    """Błąd warstwy wejścia audio (uruchomienie/odczyt/konwersja)."""

    pass


@dataclass
class CaptureConfig:
    """
    Konfiguracja wejścia audio (ALSA/WebRTC).

    Pola:
      - backend: nazwa backendu, np. "alsa"
      - device: urządzenie ALSA, np. "plughw:wm8960soundcard,0"
      - sample_rate: próbkowanie w Hz (np. 16000)
      - channels: liczba kanałów (1=mono, 2=stereo)
      - frame_ms: długość ramki w milisekundach (np. 20)
      - buffer_seconds: dodatkowy bufor dla ALSA/arecord (sekundy, może być 0.0)
      - command: (opcjonalnie) ścieżka/nazwa programu nagrywającego (domyślnie "arecord")
                 np. "arecord" lub "/usr/bin/arecord"
    """

    backend: str
    device: str
    sample_rate: int
    channels: int
    frame_ms: int
    buffer_seconds: float = 0.0
    command: str | None = None  # <-- NOWE

    # 16-bit PCM (S16_LE) → 2 bajty na próbkę
    BYTES_PER_SAMPLE: Final[int] = 2

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be > 0")
        if self.channels <= 0:
            raise ValueError("channels must be > 0")
        if self.frame_ms <= 0:
            raise ValueError("frame_ms must be > 0")
        if self.buffer_seconds < 0.0:
            self.buffer_seconds = 0.0

    @property
    def frame_duration_s(self) -> float:
        return self.frame_ms / 1000.0

    @property
    def frame_samples(self) -> int:
        return int(self.sample_rate * self.frame_duration_s)

    @property
    def frame_bytes(self) -> int:
        return self.frame_samples * self.channels * self.BYTES_PER_SAMPLE

    @property
    def buffer_time_us(self) -> int:
        return int(self.buffer_seconds * 1_000_000)

    def bytes_for_ms(self, ms: int | float) -> int:
        seconds = float(ms) / 1000.0
        samples = int(self.sample_rate * seconds)
        return samples * self.channels * self.BYTES_PER_SAMPLE


class AudioCapture:
    """
    Prosty wrapper na ciągłe przechwytywanie PCM przez ALSA (arecord → stdout).

    Użycie:
        with AudioCapture(cfg, logger) as cap:
            for frame in cap.frames():
                ...

    Zwracane ramki mają dokładnie `cfg.frame_bytes` bajtów (S16_LE).
    """

    def __init__(self, config: CaptureConfig, logger: voice_logging.VoiceLogger | None = None) -> None:
        self.config = config
        self.logger = logger or voice_logging.get_logger("voice.capture")
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()

    def __enter__(self) -> AudioCapture:
        backend = (self.config.backend or "alsa").lower()
        if backend != "alsa":
            raise CaptureError(f"Unsupported capture backend: {backend}")

        # wybór programu: config.command ma priorytet, inaczej szukamy arecord
        if self.config.command:
            cmd_head = shlex.split(self.config.command)
            path = shutil.which(cmd_head[0]) or cmd_head[0]
        else:
            path = shutil.which("arecord")

        if not path:
            raise CaptureError("arecord not found on PATH and no 'command' provided")

        cmd = [path]
        # a następnie stałe parametry do surowego PCM S16_LE
        cmd += [
            "-q",
            "-t",
            "raw",
            "-f",
            "S16_LE",
            "-c",
            str(max(1, int(self.config.channels))),
            "-r",
            str(self.config.sample_rate),
            "-D",
            self.config.device or "default",
        ]
        if self.config.buffer_time_us > 0:
            cmd += ["--buffer-time", str(self.config.buffer_time_us)]

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except Exception as exc:
            raise CaptureError(f"Failed to start capture command: {exc}") from exc

        self.logger.debug("capture.start", command=" ".join(cmd))
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._stop.set()
        proc = self._proc
        if not proc:
            return
        if proc.stdout:
            with contextlib.suppress(Exception):
                proc.stdout.close()
        if proc.stderr:
            with contextlib.suppress(Exception):
                proc.stderr.close()
        with contextlib.suppress(Exception):
            proc.terminate()
        try:
            proc.wait(timeout=1.5)
        except Exception:
            with contextlib.suppress(Exception):
                proc.kill()
        self._proc = None
        self.logger.debug("capture.stop")

    def frames(self) -> Iterator[bytes]:
        proc = self._proc
        if not proc or not proc.stdout:
            raise CaptureError("Capture not started")

        fb = int(self.config.frame_bytes)
        stdout = proc.stdout

        buf = bytearray()
        last_data_ts = time.time()

        while not self._stop.is_set():
            chunk = stdout.read(fb - len(buf))
            if not chunk:
                if proc.poll() is not None:
                    err = None
                    if proc.stderr:
                        with contextlib.suppress(Exception):
                            err = proc.stderr.read().decode("utf-8", "ignore").strip()
                    if err:
                        self.logger.warning("capture.proc.exit", returncode=proc.returncode, stderr=err)
                    break
                time.sleep(0.005)
                if (time.time() - last_data_ts) > 2.0:
                    self.logger.warning("capture.silence.timeout")
                    last_data_ts = time.time()
                continue

            last_data_ts = time.time()
            buf.extend(chunk)
            if len(buf) >= fb:
                out = bytes(buf[:fb])
                del buf[:fb]
                yield out
        return
