# apps/voice/ding.py
"""Ding/beep sound generation and playback.

Extracted from playback.py to keep files under 600 lines.
Handles beep/ding sound generation and playback functionality.
"""

from __future__ import annotations

import io
import math
import os
import wave
from pathlib import Path
from typing import TYPE_CHECKING

from . import voice_logging

if TYPE_CHECKING:
    from .playback import PlaybackConfig


def play_ding(config: "PlaybackConfig", logger: voice_logging.VoiceLogger | None = None) -> None:
    """
    Play a short "ding" sound.
    - Respects config.ding.enabled (if provided).
    - If config.ding.path exists – plays the file, otherwise generates 880 Hz ~200 ms tone.
    - Supports config.ding.gain_db for generated tone.
    """
    logger = logger or voice_logging.get_logger("voice.playback")
    ding_cfg = config.ding or {}

    # enabled: defaults to True; set False to disable
    enabled = ding_cfg.get("enabled")
    if isinstance(enabled, bool) and not enabled:
        logger.event("playback.ding.skip")
        return

    # if there's a file path – play it (without volume adjustment)
    path = ding_cfg.get("path") if isinstance(ding_cfg, dict) else None
    if isinstance(path, str) and os.path.exists(path):
        from .playback import play_file
        play_file(path, config, logger, blocking=False)
        return

    # generated tone – consider gain_db
    gain_db = 0.0
    try:
        if "gain_db" in ding_cfg:
            gain_db = float(ding_cfg["gain_db"])  # e.g. -3.0
    except Exception:
        gain_db = 0.0

    logger.event("playback.ding.generate")
    # base amplitude 0.25, scale with dB
    base_amp = 0.25
    scale = 10.0 ** (gain_db / 20.0)
    amplitude = max(0.0, min(1.0, base_amp * scale))
    audio = _tone_wav(duration=0.20, freq=880.0, sample_rate=16000, amplitude=amplitude)
    
    from .playback import play_bytes
    play_bytes(audio, "wav", config, logger, blocking=False)


def _tone_wav(duration: float, freq: float, sample_rate: int = 16000, amplitude: float = 0.25) -> bytes:
    """Return WAV bytes (mono, 16-bit) with simple sine wave."""
    frame_count = max(1, int(duration * sample_rate))
    buf = bytearray()

    # envelope 5 ms start / 40 ms end – no clicks
    fade_in_frames = min(frame_count, int(0.005 * sample_rate))
    fade_out_frames = min(frame_count, int(0.040 * sample_rate))

    for i in range(frame_count):
        if i < fade_in_frames:
            env = (i + 1) / max(1, fade_in_frames)
        elif i >= frame_count - fade_out_frames:
            env = (frame_count - i) / max(1, fade_out_frames)
        else:
            env = 1.0

        s = math.sin(2 * math.pi * freq * (i / sample_rate))
        value = int(amplitude * env * s * 32767.0)
        buf.extend(value.to_bytes(2, "little", signed=True))

    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(buf))
    return bio.getvalue()


def generate_beep_tone(
    frequency: float = 880.0,
    duration: float = 0.2,
    sample_rate: int = 16000,
    amplitude: float = 0.25,
    gain_db: float = 0.0,
) -> bytes:
    """Generate a beep tone with specified parameters.
    
    Args:
        frequency: Tone frequency in Hz
        duration: Duration in seconds
        sample_rate: Sample rate in Hz
        amplitude: Base amplitude (0.0 to 1.0)
        gain_db: Gain adjustment in dB
        
    Returns:
        WAV audio bytes
    """
    # Apply gain
    scale = 10.0 ** (gain_db / 20.0)
    adjusted_amplitude = max(0.0, min(1.0, amplitude * scale))
    
    return _tone_wav(duration, frequency, sample_rate, adjusted_amplitude)


def configure_ding_from_dict(config_dict: dict) -> dict:
    """Configure ding settings from config dictionary.
    
    Args:
        config_dict: Configuration dictionary
        
    Returns:
        Processed ding configuration
    """
    ding_cfg = config_dict.get("ding", {})
    
    # Set defaults
    defaults = {
        "enabled": True,
        "frequency": 880.0,
        "duration": 0.2,
        "gain_db": 0.0,
        "sample_rate": 16000,
        "amplitude": 0.25,
    }
    
    # Merge with user config
    for key, default_value in defaults.items():
        if key not in ding_cfg:
            ding_cfg[key] = default_value
    
    return ding_cfg