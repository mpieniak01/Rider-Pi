"""WAV/PCM audio utilities for Rider-Pi voice assistant.

Provides utilities for:
- WAV file detection and parameter reading
- Audio format conversion and resampling
- Gain adjustment
- PCM-to-WAV wrapping
- JSON audio payload decoding
"""

from __future__ import annotations

import audioop
import base64
import io
import json
import os
import shutil
import wave


def is_wav(data: bytes) -> bool:
    """Check if data is a valid WAV file.

    Args:
        data: Raw bytes to check

    Returns:
        True if data appears to be WAV format
    """
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def read_wav_params(data: bytes) -> tuple[bytes, int, int, int] | None:
    """Read WAV file parameters and extract PCM data.

    Args:
        data: WAV file bytes

    Returns:
        Tuple of (pcm_data, sample_rate, channels, sample_width) or None if invalid
    """
    try:
        if not is_wav(data):
            return None

        bio = io.BytesIO(data)
        with wave.open(bio, "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()  # bytes per sample
            sample_rate = wf.getframerate()
            pcm_data = wf.readframes(wf.getnframes())

        return pcm_data, sample_rate, channels, sample_width

    except Exception:
        return None


def wrap_wav(pcm_data: bytes, sample_rate: int, channels: int, sample_width: int = 2) -> bytes:
    """Wrap PCM data in WAV container format.

    Args:
        pcm_data: Raw PCM audio data
        sample_rate: Sample rate in Hz
        channels: Number of audio channels
        sample_width: Bytes per sample (default: 2 for 16-bit)

    Returns:
        Complete WAV file bytes
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm_data)
    return buf.getvalue()


def decode_json_audio(data: bytes) -> tuple[bytes, int | None, str | None] | None:
    """Decode audio from JSON payload with base64 encoding.

    Supports various field names: 'audio', 'data', 'bytes', 'b64', 'audio_b64'

    Args:
        data: Bytes that might contain JSON with encoded audio

    Returns:
        Tuple of (audio_bytes, sample_rate, format) or None if not JSON audio
    """
    try:
        text = data.decode("utf-8", errors="ignore").strip()
        if not (text.startswith("{") and text.endswith("}")):
            return None

        obj = json.loads(text)

        # Find audio payload
        payload = None
        for key in ("audio", "data", "bytes", "b64", "audio_b64"):
            if key in obj:
                payload = obj[key]
                break

        if payload is None:
            return None

        # Decode audio data
        raw_audio: bytes | None = None

        if isinstance(payload, str):
            try:
                raw_audio = base64.b64decode(payload)
            except Exception:
                return None

        elif isinstance(payload, dict):
            for key in ("b64", "base64", "data"):
                value = payload.get(key)
                if isinstance(value, str):
                    try:
                        raw_audio = base64.b64decode(value)
                        break
                    except Exception:
                        continue

        if raw_audio is None:
            return None

        # Extract metadata
        sample_rate = obj.get("sr") or obj.get("sample_rate")
        format_str = obj.get("fmt") or obj.get("format")

        return raw_audio, sample_rate, format_str

    except Exception:
        return None


def resample_pcm(pcm_data: bytes, from_sr: int, from_ch: int, to_sr: int, to_ch: int) -> bytes:
    """Resample PCM audio data to different sample rate and channel count.

    Args:
        pcm_data: Input PCM data (16-bit samples)
        from_sr: Input sample rate
        from_ch: Input channel count
        to_sr: Target sample rate
        to_ch: Target channel count

    Returns:
        Resampled PCM data
    """
    # Resample to target sample rate
    resampled, _ = audioop.ratecv(pcm_data, 2, from_ch, from_sr, to_sr, None)

    # Convert channel count if needed
    if to_ch == 2 and from_ch == 1:
        # Mono to stereo
        resampled = audioop.tostereo(resampled, 2, 1, 1)
    elif to_ch == 1 and from_ch == 2:
        # Stereo to mono
        resampled = audioop.tomono(resampled, 2, 0.5, 0.5)

    return resampled


def add_tail_silence(pcm_data: bytes, sample_rate: int, channels: int, tail_ms: int | None = None) -> bytes:
    """Add silence to end of PCM data.

    Args:
        pcm_data: Input PCM data
        sample_rate: Sample rate in Hz
        channels: Number of channels
        tail_ms: Milliseconds of silence to add (default from env VOICE_TAIL_MS or 120)

    Returns:
        PCM data with silence appended
    """
    tail_ms = tail_ms or int(os.environ.get("VOICE_TAIL_MS", "120"))
    silence_frames = int(sample_rate * tail_ms / 1000.0) * channels
    silence_bytes = b"\x00\x00" * silence_frames

    return pcm_data + silence_bytes


def apply_gain_wav(wav_data: bytes, gain: float) -> bytes:
    """Apply gain adjustment to WAV file.

    Args:
        wav_data: Input WAV file bytes
        gain: Gain multiplier (1.0 = no change)

    Returns:
        WAV file bytes with gain applied
    """
    if gain is None or abs(gain - 1.0) < 1e-6:
        return wav_data

    wav_params = read_wav_params(wav_data)
    if not wav_params:
        return wav_data

    pcm_data, sample_rate, channels, sample_width = wav_params

    # Only support 16-bit samples
    if sample_width != 2:
        return wav_data

    try:
        # Apply gain to PCM data
        gained_pcm = audioop.mul(pcm_data, 2, float(gain))

        # Add tail silence
        gained_pcm = add_tail_silence(gained_pcm, sample_rate, channels, None)

        # Wrap back to WAV
        return wrap_wav(gained_pcm, sample_rate, channels, 2)

    except Exception:
        return wav_data


def ensure_wav_format(audio_data: bytes, sample_rate: int, fmt: str) -> bytes:
    """Normalize audio input to proper WAV format with target rate/channels.

    Handles:
    - JSON with base64 audio
    - Existing WAV files
    - Raw PCM data

    Args:
        audio_data: Input audio bytes
        sample_rate: Expected sample rate
        fmt: Format hint

    Returns:
        Normalized WAV file bytes
    """
    target_rate = int(os.environ.get("VOICE_RATE", "48000"))
    target_channels = int(os.environ.get("VOICE_CHANNELS", "2"))

    # Try JSON decoding first
    json_result = decode_json_audio(audio_data)
    if json_result:
        audio_data, json_sr, json_fmt = json_result
        if json_sr:
            sample_rate = int(json_sr)
        if json_fmt:
            pass  # Format info available but not used in this function

    # Check if already WAV
    wav_params = read_wav_params(audio_data)
    if wav_params:
        pcm_data, in_sr, in_ch, in_sw = wav_params

        # Resample if needed
        if in_sw == 2 and (in_sr != target_rate or in_ch != target_channels):
            pcm_data = resample_pcm(pcm_data, in_sr, in_ch, target_rate, target_channels)
            in_sr, in_ch = target_rate, target_channels

        # Add tail and wrap
        pcm_data = add_tail_silence(pcm_data, in_sr, in_ch, None)
        return wrap_wav(pcm_data, in_sr, in_ch, in_sw)

    # Assume raw PCM16 mono and convert
    resampled = resample_pcm(audio_data, sample_rate, 1, target_rate, target_channels)
    resampled = add_tail_silence(resampled, target_rate, target_channels, None)
    return wrap_wav(resampled, target_rate, target_channels, 2)


def pulse_available() -> bool:
    """Check if PulseAudio is available for playback.

    Returns:
        True if PulseAudio appears to be available
    """
    return bool(
        shutil.which("paplay")
        and (os.environ.get("PULSE_SERVER") or os.path.exists(os.path.expanduser("~/.config/pulse")))
    )


def choose_player_command() -> list[str] | None:
    """Choose appropriate command-line audio player.

    Returns:
        Command and arguments as list, or None if no player found
    """
    # Environment override
    env_player = os.environ.get("VOICE_PLAYER")
    if env_player:
        return env_player.split()

    # Prefer PulseAudio if available
    if pulse_available():
        return ["paplay"]

    # Fall back to ALSA
    if shutil.which("aplay"):
        return ["aplay", "-q"]

    return None
