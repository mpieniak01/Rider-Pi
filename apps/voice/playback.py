"""Audio playback helpers for the voice assistant."""
from __future__ import annotations

import contextlib
import math
import os
import shutil
import subprocess
import tempfile
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import logging as voice_logging


class PlaybackError(RuntimeError):
    pass


@dataclass
class PlaybackConfig:
    backend: str
    alsa_device: str | None
    volume: int
    ding: dict[str, object]


def _choose_player(backend: str) -> Optional[str]:
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


def play_bytes(audio: bytes, fmt: str, config: PlaybackConfig, logger: voice_logging.VoiceLogger | None = None, *, blocking: bool = True):
    player = _choose_player(config.backend)
    if not player:
        raise PlaybackError(f"No playback command for backend {config.backend}")
    suffix = ".wav" if fmt == "wav" else f".{fmt}" if fmt else ".bin"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(audio)
    tmp_path = tmp.name
    tmp.close()
    cmd = [player, tmp_path]
    if os.path.basename(player) == "aplay" and config.alsa_device:
        cmd = [player, "-q", "-D", config.alsa_device, tmp_path]
    if os.path.basename(player) == "ffplay":
        cmd = [player, "-autoexit", "-nodisp", tmp_path]
    logger = logger or voice_logging.get_logger("voice.playback")
    logger.event("playback.start", command=" ".join(cmd))
    proc = subprocess.Popen(cmd)
    if blocking:
        proc.wait()
        logger.event("playback.done", returncode=proc.returncode)
        os.unlink(tmp_path)
        return proc.returncode == 0

    def _cleanup() -> None:
        proc.wait()
        logger.event("playback.done", returncode=proc.returncode)
        with contextlib.suppress(FileNotFoundError):  # type: ignore[name-defined]
            os.unlink(tmp_path)

    threading.Thread(target=_cleanup, daemon=True).start()
    return proc


def play_file(path: str | os.PathLike[str], config: PlaybackConfig, logger: voice_logging.VoiceLogger | None = None, *, blocking: bool = True):
    with open(path, "rb") as fh:
        data = fh.read()
    fmt = Path(path).suffix.lstrip(".") or "wav"
    return play_bytes(data, fmt, config, logger, blocking=blocking)


def play_ding(config: PlaybackConfig, logger: voice_logging.VoiceLogger | None = None) -> None:
    ding_cfg = config.ding or {}
    path = ding_cfg.get("path") if isinstance(ding_cfg, dict) else None
    if isinstance(path, str) and os.path.exists(path):
        play_file(path, config, logger, blocking=False)
        return
    logger = logger or voice_logging.get_logger("voice.playback")
    logger.event("playback.ding.generate")
    audio = _tone(0.2, 880.0)
    play_bytes(audio, "wav", config, logger, blocking=False)


def _tone(duration: float, freq: float, sample_rate: int = 16000) -> bytes:
    frame_count = int(duration * sample_rate)
    buf = bytearray()
    for i in range(frame_count):
        value = int(0.25 * math.sin(2 * math.pi * freq * (i / sample_rate)) * 32767)
        buf.extend(value.to_bytes(2, "little", signed=True))
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(buf))
    data = Path(tmp.name).read_bytes()
    os.unlink(tmp.name)
    return data
