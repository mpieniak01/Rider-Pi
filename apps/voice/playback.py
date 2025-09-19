# apps/voice/playback.py
"""Audio playback helpers for the voice assistant."""
from __future__ import annotations

import contextlib
import io
import math
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import voice_logging as voice_logging


class PlaybackError(RuntimeError):
    pass


@dataclass
class PlaybackConfig:
    backend: str = "auto"                     # "auto" | "pulse" | "alsa" | nazwa binarki
    alsa_device: str | None = None            # np. "plughw:1,0" (używane tylko z aplay)
    volume: int = 100                         # obecnie informacyjne (regulacja po stronie systemu)
    ding: dict[str, object] = field(default_factory=dict)


@dataclass
class PlaybackStream:
    process: subprocess.Popen[bytes]
    fmt: str
    backend: str
    accumulate: bool = False
    _buffer: bytearray | None = None
    _failed: bool = False

    def __post_init__(self) -> None:
        if self.accumulate:
            self._buffer = bytearray()

    def write(self, chunk: bytes) -> None:
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
        except Exception as exc:  # pragma: no cover - system-level failure
            self._failed = True
            raise PlaybackError(f"Player write failed: {exc}") from exc

    def close(self, *, timeout: float = 20.0) -> tuple[bool, bytes | None, str | None]:
        if self.process.stdin:
            with contextlib.suppress(Exception):
                self.process.stdin.close()
        try:
            rc = self.process.wait(timeout=timeout)
        except Exception:  # pragma: no cover - system-level failure
            with contextlib.suppress(Exception):
                self.process.kill()
            rc = -1
        stderr_text = None
        if self.process.stderr:
            try:
                stderr_text = self.process.stderr.read().decode("utf-8", "ignore").strip()
            except Exception:
                stderr_text = None
        audio = bytes(self._buffer) if self._buffer is not None else None
        ok = rc == 0 and not self._failed
        return ok, audio, stderr_text

def _choose_player(backend: str) -> Optional[str]:
    """Zwróć ścieżkę do binarki gracza na podstawie backendu."""
    if backend == "pulse":
        return shutil.which("paplay") or shutil.which("aplay")
    if backend == "alsa":
        return shutil.which("aplay")
    if backend == "auto":
        for cand in ("paplay", "aplay", "ffplay"):
            path = shutil.which(cand)
            if path:
                return path
        return None
    return shutil.which(backend)


def _build_cmd(player_path: str, tmp_path: str, fmt: str, alsa_device: str | None) -> List[str]:
    """Zbuduj komendę odtwarzacza dla podanej binarki."""
    base = os.path.basename(player_path)
    if base == "aplay":
        if alsa_device:
            return [player_path, "-q", "-D", alsa_device, tmp_path]
        return [player_path, "-q", tmp_path]
    if base == "ffplay":
        # ffplay niech działa bez GUI
        return [player_path, "-autoexit", "-nodisp", tmp_path]
    # paplay i inne – wystarczy ścieżka
    return [player_path, tmp_path]




def _iter_mpg123_commands(config: PlaybackConfig):
    path = shutil.which("mpg123")
    if not path:
        return []
    backend = (config.backend or "pulse").lower()
    order = []
    if backend in {"pulse", "alsa"}:
        order.append(backend)
    else:
        order.extend(["pulse", "alsa"])
    # zawsze dodaj rezerwę bez -o
    order.append("default")
    seen: set[str] = set()
    commands = []
    for item in order:
        if item in seen:
            continue
        seen.add(item)
        if item == "pulse":
            cmd = [path, "-q", "-o", "pulse", "-"]
        elif item == "alsa":
            cmd = [path, "-q", "-o", "alsa"]
            if config.alsa_device:
                cmd += ["-a", config.alsa_device]
            cmd.append("-")
        else:
            cmd = [path, "-q", "-"]
        commands.append((f"mpg123-{item}", cmd))
    return commands


def _iter_wav_commands(config: PlaybackConfig):
    commands = []
    paplay = shutil.which("paplay")
    if paplay:
        commands.append(("paplay", [paplay, "-"]))
    aplay = shutil.which("aplay")
    if aplay:
        cmd = [aplay, "-q"]
        if config.alsa_device:
            cmd += ["-D", config.alsa_device]
        cmd.append("-")
        commands.append(("aplay", cmd))
    return commands


def start_stream(
    fmt: str,
    config: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None,
    *,
    accumulate: bool = False,
) -> PlaybackStream | None:
    """Spróbuj otworzyć strumień odtwarzacza dla danego formatu."""

    logger = logger or voice_logging.get_logger("voice.playback")
    fmt = (fmt or "").lower()

    if fmt == "mp3":
        for backend, cmd in _iter_mpg123_commands(config):
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
            except FileNotFoundError:
                return None
            except Exception as exc:  # pragma: no cover - system-level failure
                logger.warning("playback.stream.start_failed", backend=backend, error=str(exc))
                continue
            logger.debug("playback.stream.start", backend=backend, command=" ".join(cmd))
            return PlaybackStream(proc, fmt="mp3", backend=backend, accumulate=accumulate)
        return None

    if fmt == "wav":
        for backend, cmd in _iter_wav_commands(config):
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
            except Exception as exc:  # pragma: no cover - system-level failure
                logger.warning("playback.stream.start_failed", backend=backend, error=str(exc))
                continue
            logger.debug("playback.stream.start", backend=backend, command=" ".join(cmd))
            return PlaybackStream(proc, fmt="wav", backend=backend, accumulate=accumulate)
        return None

    return None

def play_bytes(
    audio: bytes,
    fmt: str,
    config: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None,
    *,
    blocking: bool = True,
):
    """
    Odtwórz bajty audio zapisując je tymczasowo do pliku.
    - jeśli ustawiono VOICE_PLAYER, użyjemy go (może zawierać argumenty),
    - w przeciwnym razie wybór na podstawie config.backend.
    """
    logger = logger or voice_logging.get_logger("voice.playback")

    # 0) wybór komendy (ENV ma pierwszeństwo)
    env_player = os.getenv("VOICE_PLAYER")
    env_cmd: Optional[List[str]] = shlex.split(env_player) if env_player else None

    player_path: Optional[str] = None
    if not env_cmd:
        player_path = _choose_player(config.backend)
        if not player_path:
            raise PlaybackError(f"No playback command for backend '{config.backend}'")
    # 1) zapisz do pliku tymczasowego
    suffix = ".wav" if (fmt or "").lower() == "wav" else f".{fmt}" if fmt else ".bin"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(audio)
        tmp_path = tmp.name
    finally:
        tmp.close()

    # 2) zbuduj końcowe polecenie
    if env_cmd:
        cmd = env_cmd + [tmp_path]
    else:
        cmd = _build_cmd(player_path, tmp_path, fmt, config.alsa_device)  # type: ignore[arg-type]

    logger.event("playback.start", command=" ".join(cmd))
    proc = subprocess.Popen(cmd)

    def _cleanup() -> None:
        rc = proc.wait()
        logger.event("playback.done", returncode=rc)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)

    if blocking:
        _cleanup()
        return proc.returncode == 0

    threading.Thread(target=_cleanup, daemon=True).start()
    return proc


def play_file(
    path: str | os.PathLike[str],
    config: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None,
    *,
    blocking: bool = True,
):
    with open(path, "rb") as fh:
        data = fh.read()
    fmt = Path(path).suffix.lstrip(".").lower() or "wav"
    return play_bytes(data, fmt, config, logger, blocking=blocking)


def play_ding(config: PlaybackConfig, logger: voice_logging.VoiceLogger | None = None) -> None:
    """
    Zagraj krótki „ding”.
    - Szanuje config.ding.enabled (jeśli podane).
    - Jeśli config.ding.path istnieje – odtwarza plik, inaczej generuje ton 880 Hz ~200 ms.
    """
    logger = logger or voice_logging.get_logger("voice.playback")
    ding_cfg = config.ding or {}

    enabled = ding_cfg.get("enabled")
    if isinstance(enabled, bool) and not enabled:
        # wyraźnie wyłączone
        logger.event("playback.ding.skip")
        return

    path = ding_cfg.get("path") if isinstance(ding_cfg, dict) else None
    if isinstance(path, str) and os.path.exists(path):
        play_file(path, config, logger, blocking=False)
        return

    logger.event("playback.ding.generate")
    audio = _tone_wav(duration=0.20, freq=880.0, sample_rate=16000, amplitude=0.25)
    play_bytes(audio, "wav", config, logger, blocking=False)


# ───────────────────────────────────────────────────────────────────────────────
# Pomocnicze: generacja prostego tonu do dinga (WAV w pamięci)
# ───────────────────────────────────────────────────────────────────────────────

def _tone_wav(duration: float, freq: float, sample_rate: int = 16000, amplitude: float = 0.25) -> bytes:
    """Zwróć bajty WAV (mono, 16-bit) z prostym sinusem."""
    frame_count = max(1, int(duration * sample_rate))
    buf = bytearray()

    # proste „envelope” 5 ms na start i 40 ms na koniec, żeby uniknąć kliknięć
    fade_in_frames = min(frame_count, int(0.005 * sample_rate))
    fade_out_frames = min(frame_count, int(0.040 * sample_rate))

    for i in range(frame_count):
        # obwiednia
        if i < fade_in_frames:
            env = (i + 1) / max(1, fade_in_frames)
        elif i >= frame_count - fade_out_frames:
            env = (frame_count - i) / max(1, fade_out_frames)
        else:
            env = 1.0

        s = math.sin(2 * math.pi * freq * (i / sample_rate))
        value = int(amplitude * env * s * 32767.0)
        buf.extend(value.to_bytes(2, "little", signed=True))

    # zapisz WAV do pamięci
    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(buf))
    return bio.getvalue()
