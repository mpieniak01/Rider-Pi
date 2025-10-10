# apps/voice/cli_commands.py
"""CLI command implementations and argument parser.

Extracted from cli.py to keep files under 600 lines.
Contains parser building and command implementations.
"""

from __future__ import annotations

import argparse
import audioop
import io
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

from . import config as voice_config, voice_logging
from .asr import ASRConfig, transcribe
from .audio.playback import PlaybackConfig, play_bytes
from .tts import TTSConfig, synthesize


def build_parser() -> argparse.ArgumentParser:
    """Build the main argument parser for voice CLI."""
    parser = argparse.ArgumentParser(description="Rider voice assistant")
    parser.add_argument("--config", help="Path to config file", default=None)
    parser.add_argument("--lang", type=str, help="ASR language hint (pl|en|auto)", default=None)

    sub = parser.add_subparsers(dest="cmd")

    # Listen command
    listen = sub.add_parser("listen", help="Continuous mode")
    listen.set_defaults(func=cmd_listen)
    listen.add_argument("--mode", choices=["stream", "file"], default=None)
    listen.add_argument("--hotword", choices=["on", "off", "ptt"], default=None)
    listen.add_argument("--asr", nargs="*")
    listen.add_argument("--chat", nargs="*")
    listen.add_argument("--tts", nargs="*")
    listen.add_argument("--vad", nargs="*")
    listen.add_argument("--turn", nargs="*")
    listen.add_argument("--playback", nargs="*")
    listen.add_argument("--capture", nargs="*")
    listen.add_argument("--service", nargs="*")
    listen.add_argument("--ding", choices=["on", "off"], default=None)
    listen.add_argument("--save-audio", nargs="*")
    listen.add_argument("--log-level", default=None)

    # PTT command
    ptt = sub.add_parser("ptt", help="Push-to-talk mode")
    ptt.set_defaults(func=cmd_ptt)
    ptt.add_argument("--mode", choices=["stream", "file"], default=None)
    ptt.add_argument("--asr", nargs="*")
    ptt.add_argument("--chat", nargs="*")
    ptt.add_argument("--tts", nargs="*")
    ptt.add_argument("--vad", nargs="*")
    ptt.add_argument("--turn", nargs="*")
    ptt.add_argument("--playback", nargs="*")
    ptt.add_argument("--capture", nargs="*")
    ptt.add_argument("--ding", choices=["on", "off"], default=None)
    ptt.add_argument("--service", nargs="*")
    ptt.add_argument("--save-audio", nargs="*")
    ptt.add_argument("--log-level", default=None)

    # Once command
    once = sub.add_parser("once", help="Single cycle")
    once.set_defaults(func=cmd_once)
    once.add_argument("--mode", choices=["stream", "file"], default=None)
    once.add_argument("--hotword", choices=["on", "off", "ptt"], default=None)
    once.add_argument("--asr", nargs="*")
    once.add_argument("--chat", nargs="*")
    once.add_argument("--tts", nargs="*")
    once.add_argument("--vad", nargs="*")
    once.add_argument("--turn", nargs="*")
    once.add_argument("--playback", nargs="*")
    once.add_argument("--capture", nargs="*")
    once.add_argument("--ding", choices=["on", "off"], default=None)
    once.add_argument("--service", nargs="*")
    once.add_argument("--save-audio", nargs="*")
    once.add_argument("--log-level", default=None)

    # ASR command
    asr_cmd = sub.add_parser("asr", help="Transcribe file")
    asr_cmd.set_defaults(func=cmd_asr)
    asr_cmd.add_argument("--file", required=True)
    asr_cmd.add_argument("--asr", nargs="*")
    asr_cmd.add_argument("--log-level", default=None)

    # TTS command
    tts_cmd = sub.add_parser("tts", help="Synthesize text")
    tts_cmd.set_defaults(func=cmd_tts)
    tts_cmd.add_argument("--text", required=True)
    tts_cmd.add_argument("--play", action="store_true")
    tts_cmd.add_argument("--tts", nargs="*")
    tts_cmd.add_argument("--playback", nargs="*")
    tts_cmd.add_argument("--log-level", default=None)

    # Diagnostics command
    diag = sub.add_parser("diag", help="Diagnostics")
    diag.set_defaults(func=cmd_diag)
    diag.add_argument("--mode", choices=["stream", "file"], default=None)
    diag.add_argument("--log-level", default=None)

    return parser


def cmd_listen(args) -> None:
    """Execute listen command (continuous mode)."""
    # If hotword=ptt and no --vad provided, disable local VAD
    if getattr(args, "hotword", None) == "ptt" and not getattr(args, "vad", None):
        args.vad = ["enabled=false"]

    config, _ = _configure(args)
    from .svc_core import run_listen

    run_listen(config, args)


def cmd_ptt(args) -> None:
    """Execute PTT command (push-to-talk mode)."""
    # Force PTT mode and disable local VAD if not specified
    args.hotword = "ptt"
    if not getattr(args, "vad", None):
        args.vad = ["enabled=false"]

    config, _ = _configure(args)
    from .svc_core import run_listen

    run_listen(config, args)


def cmd_once(args) -> None:
    """Execute once command (single cycle)."""
    # If PTT mode and no --vad provided, disable local VAD
    if getattr(args, "hotword", None) == "ptt" and not getattr(args, "vad", None):
        args.vad = ["enabled=false"]

    config, _ = _configure(args)
    from .svc_core import run_once

    run_once(config, args)


def cmd_asr(args) -> None:
    """Execute ASR command (transcribe file)."""
    path = Path(args.file)
    with wave.open(str(path), "rb") as wf:
        sample_rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    overrides = _build_overrides(args)
    config = voice_config.load(args.config, overrides=overrides)
    voice_logging.configure(config.get("logging", {}).get("level"))

    transcript = transcribe(frames, sample_rate, ASRConfig(**_filter_for_dataclass(config["asr"], ASRConfig)))
    print(transcript.text)


def cmd_tts(args) -> None:
    """Execute TTS command (synthesize text)."""
    # Silence logs for stdout output without TTY
    if not args.play and not sys.stdout.isatty():
        _silence_logging_for_stdout()

    config, _ = _configure(args)
    audio, sample_rate, fmt = _synthesize_bytes(args.text, config["tts"])

    if args.play:
        play_bytes(audio, fmt, PlaybackConfig(**config["playback"]))
    else:
        wav_bytes = _ensure_wav_bytes(audio, sample_rate, fmt)
        # Optional gain adjustment via VOICE_GAIN env
        try:
            g = float(os.environ.get("VOICE_GAIN", "1.0"))
        except Exception:
            g = 1.0
        if g and abs(g - 1.0) > 1e-6:
            wav_bytes = _apply_gain_wav(wav_bytes, g)
        sys.stdout.buffer.write(wav_bytes)


def cmd_diag(args) -> None:
    """Execute diagnostics command."""
    overrides = _build_overrides(args)
    config = voice_config.load(getattr(args, "config", None), overrides=overrides)
    voice_logging.configure(config.get("logging", {}).get("level"))

    capture_backend = config.get("capture", {}).get("backend", "alsa")
    print("Capture backend:", capture_backend)

    if capture_backend == "alsa" and shutil.which("arecord"):
        print("arecord available: YES")
        try:
            result = subprocess.run(
                ["arecord", "--list-devices"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.stdout:
                print("ALSA devices:")
                for line in result.stdout.splitlines():
                    if "card" in line.lower() or "device" in line.lower():
                        print(f"  {line}")
        except Exception as e:
            print(f"Error listing ALSA devices: {e}")
    else:
        print("arecord available: NO")

    # Check mode detection
    from .svc_core import _wants_stream

    wants_stream = _wants_stream(config, args)
    mode = "stream" if wants_stream else "file"
    print(f"Detected mode: {mode}")

    # Show key config sections
    for section in ["asr", "chat", "tts"]:
        if section in config:
            transport = config[section].get("transport", "unknown")
            backend = config[section].get("backend", "unknown")
            print(f"{section}: backend={backend}, transport={transport}")


def _configure(args) -> tuple[dict[str, Any], Any]:
    """Configure system from arguments."""
    overrides = _build_overrides(args)
    config = voice_config.load(getattr(args, "config", None), overrides=overrides)
    voice_logging.configure(config.get("logging", {}).get("level"))
    return config, None


def _build_overrides(args) -> dict[str, Any]:
    """Build configuration overrides from CLI arguments."""
    overrides: dict[str, Any] = {}

    # Handle mode override
    if getattr(args, "mode", None):
        mode = args.mode
        if mode == "stream":
            overrides.update(
                {
                    "asr": {"transport": "realtime"},
                    "chat": {"transport": "realtime"},
                    "tts": {"transport": "realtime"},
                }
            )
        elif mode == "file":
            overrides.update(
                {
                    "asr": {"transport": "file"},
                    "chat": {"transport": "file"},
                    "tts": {"transport": "file"},
                }
            )

    # Handle other argument mappings
    for section in ["asr", "chat", "tts", "vad", "turn", "playback", "capture", "service"]:
        if hasattr(args, section) and getattr(args, section) is not None:
            values = getattr(args, section)
            if values:
                section_overrides = {}
                for value in values:
                    if "=" in value:
                        key, val = value.split("=", 1)
                        # Try to parse as appropriate type
                        if val.lower() in ("true", "false"):
                            val = val.lower() == "true"
                        elif val.isdigit():
                            val = int(val)
                        elif "." in val and val.replace(".", "").isdigit():
                            val = float(val)
                        section_overrides[key] = val
                if section_overrides:
                    overrides[section] = section_overrides

    # Handle special arguments
    if getattr(args, "hotword", None):
        if "service" not in overrides:
            overrides["service"] = {}
        if args.hotword == "ptt":
            overrides["service"]["hotword_engine"] = "ptt"
        elif args.hotword == "off":
            overrides["service"]["hotword_enabled"] = False
        elif args.hotword == "on":
            overrides["service"]["hotword_enabled"] = True

    if getattr(args, "ding", None):
        if "playback" not in overrides:
            overrides["playback"] = {}
        if "ding" not in overrides["playback"]:
            overrides["playback"]["ding"] = {}
        overrides["playback"]["ding"]["enabled"] = args.ding == "on"

    if getattr(args, "lang", None):
        if "asr" not in overrides:
            overrides["asr"] = {}
        overrides["asr"]["language"] = args.lang

    return overrides


def _filter_for_dataclass(config_dict: dict[str, Any], dataclass_type) -> dict[str, Any]:
    """Filter config dict to only include fields valid for the given dataclass."""
    import dataclasses

    if not dataclasses.is_dataclass(dataclass_type):
        filtered = dict(config_dict)
        filtered.pop("transport", None)
        return filtered

    field_names = {f.name for f in dataclasses.fields(dataclass_type)}
    filtered = {k: v for k, v in config_dict.items() if k in field_names}
    return filtered


def _synthesize_bytes(text: str, tts_config: dict[str, Any]) -> tuple[bytes, int, str]:
    """Synthesize text to audio bytes."""
    return synthesize(text, TTSConfig(**_filter_for_dataclass(tts_config, TTSConfig)))


def _ensure_wav_bytes(audio: bytes, sample_rate: int, fmt: str) -> bytes:
    """Ensure audio data is in WAV format."""
    if fmt == "wav":
        return audio

    # Convert PCM to WAV
    if fmt in ("pcm", "pcm16"):
        channels = 1  # Assume mono
        sampwidth = 2  # 16-bit

        output = io.BytesIO()
        with wave.open(output, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(sample_rate)
            wf.writeframes(audio)
        return output.getvalue()

    return audio


def _apply_gain_wav(wav_bytes: bytes, gain: float) -> bytes:
    """Apply gain to WAV audio data."""
    if abs(gain - 1.0) < 1e-6:
        return wav_bytes

    try:
        input_io = io.BytesIO(wav_bytes)
        with wave.open(input_io, "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            params = wf.getparams()

        # Apply gain
        gained_frames = audioop.mul(frames, 2, gain)  # Assume 16-bit

        # Write back to WAV
        output_io = io.BytesIO()
        with wave.open(output_io, "wb") as wf:
            wf.setparams(params)
            wf.writeframes(gained_frames)

        return output_io.getvalue()
    except Exception:
        return wav_bytes


def _silence_logging_for_stdout() -> None:
    """Silence logging when outputting to stdout."""
    import logging

    logging.getLogger().setLevel(logging.CRITICAL)
