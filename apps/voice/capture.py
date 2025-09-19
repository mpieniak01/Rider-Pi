""""Audio capture utilities for the voice assistant."""
from __future__ import annotations

import contextlib
import shlex
import subprocess
import threading
from collections.abc import Generator
from dataclasses import dataclass

from . import logging as voice_logging

_SAMPLE_WIDTH = 2  # signed 16-bit PCM


class CaptureError(RuntimeError):
    pass


@dataclass
class CaptureConfig:
    # Bezpieczne domyślne wartości
    sample_rate: int = 16000
    frame_ms: int = 20
    backend: str = "pulse"          # "pulse" | "alsa" | "command"
    device: str | None = None       # np. "hw:1,0" dla ALSA lub nazwa źródła Pulse
    buffer_seconds: float = 0.0
    channels: int = 1               # liczba kanałów (1 = mono)
    command: str | None = None      # tylko dla backend="command"

    @property
    def frame_bytes(self) -> int:
        # liczba próbek w ramce * szerokość próbki * liczba kanałów
        samples_per_frame = int(self.sample_rate * self.frame_ms / 1000)
        return samples_per_frame * _SAMPLE_WIDTH * max(1, int(self.channels))


class AudioCapture:
    """Thin wrapper around ``arecord``/``parec`` subprocesses."""

    def __init__(self, config: CaptureConfig, logger: voice_logging.VoiceLogger | None = None):
        self.config = config
        self.logger = logger or voice_logging.get_logger("voice.capture")
        self._proc: subprocess.Popen[bytes] | None = None
        self._stop = threading.Event()

    def __enter__(self) -> AudioCapture:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def start(self) -> None:
        if self._proc and self._proc.poll() is None:
            return
        cmd = self._build_command()
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except FileNotFoundError as exc:
            raise CaptureError(f"Executable not found for capture backend: {cmd[0]}") from exc
        self._stop.clear()
        self.logger.debug("capture.start", command=" ".join(map(shlex.quote, cmd)))

    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        if not proc:
            return
        if proc.poll() is None:
            with contextlib.suppress(Exception):
                proc.terminate()
                proc.wait(timeout=1.0)
        with contextlib.suppress(Exception):
            proc.kill()
        self._proc = None

    def _build_command(self) -> list[str]:
        cfg = self.config
        backend = cfg.backend.lower()

        if backend == "command" and cfg.command:
            return shlex.split(cfg.command)

        if backend == "pulse":
            cmd = [
                "parec",
                "--raw",
                "--format=s16le",
                f"--rate={cfg.sample_rate}",
                f"--channels={max(1, int(cfg.channels))}",
            ]
            if cfg.device:
                cmd.append(f"--device={cfg.device}")
            return cmd

        if backend == "alsa":
            device = cfg.device or "default"
            cmd = [
                "arecord",
                "-q",
                "-f", "S16_LE",
                "-c", str(max(1, int(cfg.channels))),
                "-r", str(cfg.sample_rate),
                "-D", device,
            ]
            buffer_us = int(max(0.0, float(cfg.buffer_seconds)) * 1_000_000)
            if buffer_us > 0:
                cmd += ["--buffer-time", str(buffer_us)]
            return cmd

        raise CaptureError(f"Unsupported capture backend: {backend}")

    def frames(self) -> Generator[bytes, None, None]:
        """
        Zwraca *dokładnie pełne ramki* (frame_bytes).
        Buforuje odczyt z potoku, żeby VAD nie dostawał za krótkich bloków.
        """
        proc = self._ensure_proc()
        frame_size = self.config.frame_bytes
        buf = bytearray()
        # czytamy większymi porcjami z pipe'a; minimum to rozmiar ramki
        read_chunk = max(frame_size, 4096)
        while not self._stop.is_set():
            chunk = proc.stdout.read(read_chunk)  # type: ignore[union-attr]
            if not chunk:
                # spuść pełne ramki, które ewentualnie zostały w buforze
                while len(buf) >= frame_size:
                    yield bytes(buf[:frame_size])
                    del buf[:frame_size]
                break
            buf.extend(chunk)
            while len(buf) >= frame_size:
                yield bytes(buf[:frame_size])
                del buf[:frame_size]

    def record(self, duration_s: float) -> bytes:
        """Record raw PCM audio for a fixed duration."""
        frame_count = max(1, int(duration_s * 1000 / self.config.frame_ms))
        buf = bytearray()
        for _, frame in zip(range(frame_count), self.frames()):
            buf.extend(frame)
        return bytes(buf)

    def record_with_vad(self, vad, *, max_frames: int | None = None) -> bytes:
        frames: list[bytes] = []
        for chunk in self.frames():
            frames.append(chunk)
            if vad(chunk):
                break
            if max_frames and len(frames) >= max_frames:
                break
        return b"".join(frames)

    def read(self, size: int) -> bytes:
        proc = self._ensure_proc()
        data = proc.stdout.read(size)  # type: ignore[union-attr]
        return data or b""

    def drain(self) -> None:
        proc = self._proc
        if proc and proc.stdout:
            with contextlib.suppress(Exception):
                proc.stdout.read()

    def _ensure_proc(self) -> subprocess.Popen[bytes]:
        if not self._proc or self._proc.poll() is not None:
            self.start()
        assert self._proc is not None
        assert self._proc.stdout is not None
        return self._proc


def capture_once(config: CaptureConfig, duration_s: float) -> bytes:
    with AudioCapture(config) as cap:
        return cap.record(duration_s)
