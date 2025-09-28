"""Audio playback utilities for Rider-Pi voice assistant.

Provides clean, focused playback functionality without complex caching.
"""

from __future__ import annotations

import contextlib
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
    backend: str = "auto"  # "auto" | "pulse" | "alsa" | command name
    alsa_device: str | None = None  # e.g., "plughw:wm8960soundcard,0"
    device: str | None = None  # alias from config
    volume: int = 100  # informational only
    ding: dict[str, Any] = field(default_factory=dict)

    def resolved_alsa_device(self) -> str | None:
        """Get resolved ALSA device name."""
        device_name = self.alsa_device or self.device
        return resolved_alsa(device_name)


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

        self._closer_thread = threading.Thread(
            target=_closer, name="playback-idle-closer", daemon=True
        )
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
            # Force kill if hanging
            with contextlib.suppress(Exception):
                self.process.kill()
            rc = -1

        stdout_data = None
        stderr_data = None
        
        # Capture any output
        if self.process.stdout:
            with contextlib.suppress(Exception):
                stdout_data = self.process.stdout.read()
        if self.process.stderr:
            with contextlib.suppress(Exception):
                stderr_data = self.process.stderr.read()

        success = rc == 0 and not self._failed
        output = self._buffer[:] if self._buffer else stdout_data
        
        return success, output, stderr_data.decode(errors="ignore") if stderr_data else None


def _iter_mpg123_commands(config: PlaybackConfig):
    """Generate mpg123 command variants for streaming."""
    path = shutil.which("mpg123")
    if not path:
        return []
        
    backend = (config.backend or "pulse").lower()
    
    # Try backends in order
    backends = []
    if backend in {"pulse", "alsa"}:
        backends.append(backend)
    else:
        backends.extend(["pulse", "alsa"])
    backends.append("default")  # fallback
    
    commands = []
    seen = set()
    
    for backend_name in backends:
        if backend_name in seen:
            continue
        seen.add(backend_name)
        
        if backend_name == "pulse":
            cmd = [path, "-q", "-o", "pulse", "-"]
        elif backend_name == "alsa":
            cmd = [path, "-q", "-o", "alsa"]
            device = config.resolved_alsa_device()
            if device:
                cmd += ["-a", device]
            cmd.append("-")
        else:  # default
            cmd = [path, "-q", "-"]
            
        commands.append(cmd)
        
    return commands


def _iter_aplay_commands(config: PlaybackConfig):
    """Generate aplay command variants."""
    path = shutil.which("aplay")
    if not path:
        return []
        
    commands = []
    device = config.resolved_alsa_device()
    
    if device:
        commands.append([path, "-q", "-D", device])
    commands.append([path, "-q"])  # system default
    
    return commands


def _iter_paplay_commands(config: PlaybackConfig):
    """Generate paplay command variants.""" 
    path = shutil.which("paplay")
    if not path:
        return []
    return [[path]]


def _start_playback_process(
    fmt: str,
    config: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None
) -> subprocess.Popen[bytes] | None:
    """Start appropriate playback process for format."""
    if logger is None:
        logger = voice_logging.get_logger(__name__)
    
    backend = (config.backend or "auto").lower()
    
    # Determine command generators based on format and backend
    if fmt == "mp3":
        command_generators = [
            lambda: _iter_mpg123_commands(config)
        ]
    else:  # pcm16, wav, etc.
        if backend == "pulse":
            command_generators = [
                lambda: _iter_paplay_commands(config),
                lambda: _iter_aplay_commands(config)
            ]
        elif backend == "alsa":
            command_generators = [
                lambda: _iter_aplay_commands(config),
                lambda: _iter_paplay_commands(config)
            ]
        else:  # auto
            command_generators = [
                lambda: _iter_paplay_commands(config),
                lambda: _iter_aplay_commands(config),
                lambda: _iter_mpg123_commands(config)
            ]
    
    # Try commands in order
    last_error = None
    for generator in command_generators:
        for cmd in generator():
            try:
                logger.event("playback.process.trying", cmd=cmd[:2])  # don't log full command
                
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0
                )
                
                logger.event("playback.process.started", cmd=cmd[0], fmt=fmt)
                return proc
                
            except Exception as e:
                last_error = str(e)
                logger.event("playback.process.failed", cmd=cmd[0], error=str(e))
                continue
                
    logger.event("playback.process.no_working_command", 
                last_error=last_error, fmt=fmt, backend=backend)
    return None


def start_stream(
    fmt: str,
    config: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None,
    *,
    accumulate: bool = False,
) -> PlaybackStream | None:
    """Start streaming playback process.
    
    Args:
        fmt: Audio format ("pcm16", "mp3", etc.)
        config: Playback configuration
        logger: Logger instance
        accumulate: If True, buffer written data
        
    Returns:
        PlaybackStream instance or None if failed
    """
    if logger is None:
        logger = voice_logging.get_logger(__name__)
        
    process = _start_playback_process(fmt, config, logger)
    if not process:
        return None
        
    return PlaybackStream(
        process=process,
        fmt=fmt,
        backend=config.backend or "auto",
        accumulate=accumulate
    )


def play_bytes(
    audio_data: bytes,
    fmt: str,
    config: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None
) -> bool:
    """Play audio bytes immediately (one-shot playback).
    
    Args:
        audio_data: Audio data to play
        fmt: Format of audio data
        config: Playback configuration
        logger: Logger instance
        
    Returns:
        True if playback succeeded
    """
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
    """Play notification ding sound.
    
    Args:
        config: Playback configuration
        logger: Logger instance
        
    Returns:
        True if ding played successfully
    """
    if logger is None:
        logger = voice_logging.get_logger(__name__)
        
    # Generate simple ding tone (440Hz for 200ms)
    sample_rate = 16000
    duration = 0.2  # seconds
    frequency = 440  # Hz
    
    import math
    samples = int(sample_rate * duration)
    
    # Generate sine wave
    ding_data = bytearray()
    for i in range(samples):
        t = i / sample_rate
        sample = int(32767 * 0.3 * math.sin(2 * math.pi * frequency * t))
        # Convert to 16-bit little-endian
        ding_data.extend(sample.to_bytes(2, 'little', signed=True))
    
    return play_bytes(bytes(ding_data), "pcm16", config, logger)


def play_file(
    file_path: Path | str,
    config: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None
) -> bool:
    """Play audio file.
    
    Args:
        file_path: Path to audio file
        config: Playback configuration  
        logger: Logger instance
        
    Returns:
        True if file played successfully
    """
    if logger is None:
        logger = voice_logging.get_logger(__name__)
        
    path = Path(file_path)
    if not path.exists():
        logger.event("playback.file.not_found", path=str(path))
        return False
        
    try:
        # Determine format from extension
        suffix = path.suffix.lower()
        if suffix == ".mp3":
            fmt = "mp3"
        elif suffix in (".wav", ".wave"):
            fmt = "wav"
        else:
            fmt = "pcm16"  # assume raw PCM
            
        # Read and play file
        audio_data = path.read_bytes()
        return play_bytes(audio_data, fmt, config, logger)
        
    except Exception as e:
        logger.event("playback.file.error", path=str(path), error=str(e))
        return False