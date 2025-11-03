""" "Audio playback utilities for Rider-Pi voice assistant.

Provides clean, focused playback functionality without complex caching.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import voice_logging as voice_logging
from ..errors import PlaybackError
from .alsa import resolved_alsa


@dataclass
class PlaybackConfig:
    """Configuration for audio playback."""

    # accepted: "auto" | "pulse" | "alsa" | "aplay" | "paplay"
    backend: str = "auto"
    # ALSA device/PCM do bezpośredniego użycia (np. "wm8960_out" albo "plughw:0,0")
    alsa_device: str | None = None
    # alias z pliku konfiguracyjnego (np. "wm8960_out")
    device: str | None = None
    volume: int = 100
    ding: dict[str, Any] = field(default_factory=dict)

    def resolved_alsa_device(self) -> str | None:
        """
        Zwraca sensowną nazwę ALSA do użycia z -D (aplay) / -a (mpg123):
        - preferuj to, co jawnie ustawiono w alsa_device
        - jeśli nie ma, spróbuj aliasu z 'device'
        - przepuść przez mapowanie resolved_alsa (jeśli istnieje)
        """
        dev = self.alsa_device or self.device
        if not dev:
            return None
        return resolved_alsa(dev) or dev


@dataclass
class PlaybackStream:
    """Streaming audio playback process wrapper."""

    process: subprocess.Popen[bytes]
    fmt: str
    backend: str
    accumulate: bool = False
    _buffer: bytearray | None = None
    _failed: bool = False
    _last_write_ts: float = field(default_factory=lambda: time.time())
    _idle_timeout_s: float = 2.0
    _closer_thread: threading.Thread | None = None
    _closer_stop: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        if self.accumulate:
            self._buffer = bytearray()

        # Auto-close on idle
        def _closer():
            while not self._closer_stop.is_set():
                if time.time() - self._last_write_ts > self._idle_timeout_s:
                    try:
                        self.close(timeout=3.0)
                    except Exception:
                        pass
                    break
                time.sleep(0.1)

        self._closer_thread = threading.Thread(target=_closer, name="playback-idle-closer", daemon=True)
        self._closer_thread.start()

    def write(self, chunk: bytes) -> None:
        """Write audio chunk to playback stream."""
        if not chunk:
            return

        if self._buffer is not None:
            self._buffer.extend(chunk)

        if not self.process.stdin:
            self._failed = True
            raise PlaybackError("Player stdin unavailable")

        try:
            self.process.stdin.write(chunk)
            self.process.stdin.flush()
            self._last_write_ts = time.time()
        except Exception as exc:
            self._failed = True
            raise PlaybackError(f"Player write failed: {exc}") from exc

    def close(self, *, timeout: float = 20.0) -> tuple[bool, bytes | None, str | None]:
        """Close playback stream and return result."""
        # Stop watchdog
        self._closer_stop.set()
        if self._closer_thread and self._closer_thread.is_alive():
            with contextlib.suppress(Exception):
                self._closer_thread.join(timeout=0.2)

        # Close stdin
        if self.process.stdin and not self.process.stdin.closed:
            with contextlib.suppress(Exception):
                self.process.stdin.close()

        try:
            rc = self.process.wait(timeout=timeout)
        except Exception:
            with contextlib.suppress(Exception):
                self.process.kill()
            rc = -1

        stdout_data = None
        stderr_data = None

        if self.process.stdout:
            with contextlib.suppress(Exception):
                stdout_data = self.process.stdout.read()
        if self.process.stderr:
            with contextlib.suppress(Exception):
                stderr_data = self.process.stderr.read()

        success = rc == 0 and not self._failed
        output = self._buffer[:] if self._buffer else stdout_data

        return (
            success,
            output,
            stderr_data.decode(errors="ignore") if stderr_data else None,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _normalize_backend(name: str) -> str:
    b = (name or "auto").lower()
    if b == "aplay":
        return "alsa"
    if b == "paplay":
        return "pulse"
    return b


def _iter_paplay_commands(_: PlaybackConfig):
    """paplay for WAV/PCM (PulseAudio/PipeWire)."""
    path = shutil.which("paplay")
    if not path:
        return []
    return [[path]]


def _unique(seq):
    seen = set()
    out = []
    for x in seq:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _iter_aplay_commands(cfg: PlaybackConfig, *, fmt: str | None):
    """
    aplay dla WAV/PCM. Kolejność:
      1) -D <alias/alsa_device> (np. wm8960_out / plughw:…)
      2) -D default
      3) -D plug:default
      4) bez -D (system default)
    """
    path = shutil.which("aplay")
    if not path:
        return []

    # Parametry dla surowego PCM (np. 'ding' 16k/mono)
    params_pcm16 = ["-f", "S16_LE", "-r", "16000", "-c", "1"]

    # === POCZĄTEK POPRAWKI ===
    # Parametry dla plików WAV. Zakładamy, że tts.py (OpenAI/Google)
    # i web.py (local) dostarczają audio 48kHz, S16_LE, 2 kanały (stereo).
    # Podajemy to jawnie, aby uniknąć błędów 'aplay' przy czytaniu nagłówka ze strumienia.
    params_wav_48k_stereo = ["-f", "S16_LE", "-r", "48000", "-c", "2"]
    # === KONIEC POPRAWKI ===

    # zbuduj kandydatów urządzeń
    preferred = []
    # najpierw alias/alsa z configu
    if cfg.device:
        preferred.append(cfg.device)
    if cfg.alsa_device and cfg.alsa_device != cfg.device:
        preferred.append(cfg.alsa_device)
    # typowe fallbacki
    preferred += ["default", "plug:default", None]
    preferred = _unique(preferred)

    commands = []
    for dev in preferred:
        base = [path, "-q"]
        if dev:
            base += ["-D", dev]

        # dobierz parametry
        if fmt == "pcm16":
            commands.append(base + params_pcm16)
        elif fmt == "wav":
            # === POCZĄTEK POPRAWKI ===
            # Użyj jawnych parametrów dla WAV
            commands.append(base + params_wav_48k_stereo)
            # === KONIEC POPRAWKI ===
        else:
            # Fallback - stary kod (może być potrzebny dla mp3?)
            commands.append(base[:])

    return commands


def _iter_mpg123_commands(cfg: PlaybackConfig):
    """mpg123 for MP3. Najpierw Pulse, potem ALSA (+alias)."""
    path = shutil.which("mpg123")
    if not path:
        return []

    cmds = []
    # Pulse output (nie potrzebuje -a)
    cmds.append([path, "-q", "-o", "pulse", "-"])

    # ALSA output; spróbuj z konkretnym PCM/dev
    devs = _unique([cfg.resolved_alsa_device(), cfg.device, None])
    for d in devs:
        if d:
            cmds.append([path, "-q", "-o", "alsa", "-a", d, "-"])
        else:
            cmds.append([path, "-q", "-o", "alsa", "-"])

    return cmds


def _iter_ffplay_commands():
    """ffplay fallback (FFmpeg)."""
    path = shutil.which("ffplay")
    if not path:
        return []
    return [[path, "-nodisp", "-autoexit", "-v", "error", "-i", "-"]]


def _iter_sox_play_commands(fmt_hint: str):
    """SoX play fallback."""
    path = shutil.which("play")
    if not path:
        return []
    if fmt_hint == "pcm16":
        return [[path, "-q", "-t", "s16", "-r", "16000", "-c", "1", "-"]]
    return [[path, "-q", "-"]]


def _start_playback_process(
    fmt: str, config: PlaybackConfig, logger: voice_logging.VoiceLogger | None = None
) -> tuple[subprocess.Popen[bytes] | None, str]:
    """Start appropriate playback process. Returns (proc, resolved_backend)."""
    if logger is None:
        logger = voice_logging.get_logger(__name__)

    backend = _normalize_backend(config.backend)

    # Log playback device information at INFO level for diagnostics
    if logger.isEnabledFor(logging.INFO):
        resolved_dev = config.resolved_alsa_device()
        logger.info(
            f"playback.device.init: backend='{backend}', "
            f"device='{resolved_dev or config.device or 'default'}', "
            f"volume={config.volume}, format='{fmt}'"
        )

    # MP3
    if fmt == "mp3":
        generators = [
            lambda: _iter_mpg123_commands(config),
            _iter_ffplay_commands,
            lambda: _iter_sox_play_commands("mp3"),
        ]
    else:
        # WAV/PCM
        if backend == "pulse":
            generators = [
                lambda: _iter_paplay_commands(config),
                # === POCZĄTEK POPRAWKI: Przekazuj 'fmt' poprawnie ===
                lambda: _iter_aplay_commands(config, fmt=fmt),
                # === KONIEC POPRAWKI ===
                _iter_ffplay_commands,
                lambda: _iter_sox_play_commands(fmt),
            ]
        elif backend == "alsa":
            generators = [
                # === POCZĄTEK POPRAWKI: Przekazuj 'fmt' poprawnie ===
                lambda: _iter_aplay_commands(config, fmt=fmt),
                # === KONIEC POPRAWKI ===
                lambda: _iter_paplay_commands(config),
                _iter_ffplay_commands,
                lambda: _iter_sox_play_commands(fmt),
            ]
        else:  # auto → preferuj ALSA najpierw (Twoje środowisko tak działa)
            generators = [
                # === POCZĄTEK POPRAWKI: Przekazuj 'fmt' poprawnie ===
                lambda: _iter_aplay_commands(config, fmt=fmt),
                # === KONIEC POPRAWKI ===
                lambda: _iter_paplay_commands(config),
                _iter_ffplay_commands,
                lambda: _iter_sox_play_commands(fmt),
            ]

    last_error = None
    for gen in generators:
        for cmd in gen():
            try:
                logger.event("playback.process.trying", cmd=cmd[:2])
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
                logger.event("playback.process.started", cmd=cmd[0], fmt=fmt)
                return proc, backend
            except Exception as e:
                last_error = str(e)
                logger.event("playback.process.failed", cmd=cmd[0], error=str(e))
                continue

    logger.event(
        "playback.process.no_working_command",
        last_error=last_error,
        fmt=fmt,
        backend=backend,
    )
    return None, backend


def start_stream(
    fmt: str,
    config: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None,
    *,
    accumulate: bool = False,
) -> PlaybackStream | None:
    """Start streaming playback process.

    Args:
        fmt: "pcm16" | "wav" | "mp3"
        config: Playback configuration
        logger: Logger instance
        accumulate: If True, buffer written data

    Returns:
        PlaybackStream or None
    """
    if logger is None:
        logger = voice_logging.get_logger(__name__)

    process, resolved_backend = _start_playback_process(fmt, config, logger)
    if not process:
        return None

    return PlaybackStream(process=process, fmt=fmt, backend=resolved_backend, accumulate=accumulate)


def play_bytes(
    audio_data: bytes,
    fmt: str,
    config: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None,
) -> bool:
    """Play audio bytes immediately (one-shot playback)."""
    if not audio_data:
        return True

    if logger is None:
        logger = voice_logging.get_logger(__name__)

    stream = start_stream(fmt, config, logger)
    if not stream:
        logger.event("playback.bytes.no_stream", fmt=fmt)
        return False

    try:
        stream.write(audio_data)
        success, _, error = stream.close()

        if not success and error:
            logger.event("playback.bytes.error", error=error[:200])

        return success

    except Exception as e:
        logger.event("playback.bytes.exception", error=str(e))
        return False


def play_ding(config: PlaybackConfig, logger: voice_logging.VoiceLogger | None = None) -> bool:
    """Play notification ding sound (440Hz, 200ms, PCM16/16k)."""
    if logger is None:
        logger = voice_logging.get_logger(__name__)

    sample_rate = 16000
    duration = 0.2
    frequency = 440

    import math

    samples = int(sample_rate * duration)
    ding_data = bytearray()
    for i in range(samples):
        t = i / sample_rate
        sample = int(32767 * 0.3 * math.sin(2 * math.pi * frequency * t))
        ding_data.extend(sample.to_bytes(2, "little", signed=True))

    return play_bytes(bytes(ding_data), "pcm16", config, logger)


def play_file(
    file_path: Path | str,
    config: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None,
) -> bool:
    """Play audio file."""
    if logger is None:
        logger = voice_logging.get_logger(__name__)

    path = Path(file_path)
    if not path.exists():
        logger.event("playback.file.not_found", path=str(path))
        return False

    try:
        suffix = path.suffix.lower()
        if suffix == ".mp3":
            fmt = "mp3"
        elif suffix in (".wav", ".wave"):
            fmt = "wav"
        else:
            fmt = "pcm16"  # assume raw PCM

        audio_data = path.read_bytes()
        return play_bytes(audio_data, fmt, config, logger)

    except Exception as e:
        logger.event("playback.file.error", path=str(path), error=str(e))
        return False
