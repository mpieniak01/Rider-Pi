# apps/voice/ding.py
"""Ding/beep sound generation and playback.

Extracted from playback.py to keep files under 600 lines.
Handles beep/ding sound generation and playback functionality.
"""

from __future__ import annotations

import io
import math
import wave
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


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
