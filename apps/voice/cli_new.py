"""Refactored CLI for Rider-Pi voice assistant (CLI-first approach).

Focused on dispatch and argument parsing, with ALSA pre-flight checks.
Audio utilities moved to audio.wavutil, ALSA checks to audio.alsa.
"""

from __future__ import annotations

import argparse
import os
import sys
import wave
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from . import config as voice_config, voice_logging
from .asr import ASRConfig, transcribe
from .audio.alsa import ensure_free, reset_streams
from .audio.playback import PlaybackConfig, play_bytes
from .audio.wavutil import apply_gain_wav, choose_player_command, ensure_wav_format
from .errors import ALSAError
from .tts import TTSConfig, synthesize


def _filter_for_dataclass(config_dict: dict[str, Any], dataclass_type) -> dict[str, Any]:
    """Filter config dict to only include fields that are valid for the given dataclass."""
    import dataclasses

    if not dataclasses.is_dataclass(dataclass_type):
        # Fallback for non-dataclass types - just remove transport
        filtered = dict(config_dict)
        filtered.pop("transport", None)
        return filtered

    valid_fields = {field.name for field in dataclasses.fields(dataclass_type)}
    return {k: v for k, v in config_dict.items() if k in valid_fields}


def _configure(args) -> tuple[dict[str, Any], None]:
    """Load config with overrides and setup logging."""
    overrides = _build_overrides(args)
    config = voice_config.load(getattr(args, "config", None), overrides=overrides)
    voice_logging.configure(config.get("logging", {}).get("level"))
    return config, None


def _build_overrides(args) -> dict[str, Any]:
    """Build configuration overrides from CLI arguments."""
    overrides: dict[str, Any] = {}
    
    # Standard section overrides  
    for section in ["asr", "chat", "tts", "vad", "turn", "playback", "capture", "service"]:
        if hasattr(args, section) and getattr(args, section):
            overrides = _merge_dict(overrides, 
                                  voice_config.override_from_pairs(section, getattr(args, section)))
    
    # Mode overrides (STRICT)
    mode = getattr(args, "mode", None)
    if mode == "stream":
        overrides = _merge_dict(overrides, {
            "asr": {"transport": "realtime"},
            "chat": {"transport": "realtime"},
            "tts": {"transport": "realtime"}
        })
    elif mode == "file":
        overrides = _merge_dict(overrides, {
            "asr": {"transport": "file"},
            "chat": {"transport": "file"},
            "tts": {"transport": "file"}
        })
    
    # Other overrides
    if hasattr(args, "lang") and args.lang:
        overrides = _merge_dict(overrides, {"asr": {"language": args.lang}})
    if hasattr(args, "hotword") and args.hotword:
        overrides = _merge_dict(overrides, {"hotword": {"engine": args.hotword}})
    if hasattr(args, "ding") and args.ding:
        overrides = _merge_dict(overrides, {"service": {"beep": args.ding == "on"}})
    if hasattr(args, "log_level") and args.log_level:
        overrides = _merge_dict(overrides, {"logging": {"level": args.log_level.upper()}})
    
    return overrides


def _merge_dict(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries."""
    result = base.copy()
    for key, value in extra.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def _alsa_preflight(config: dict[str, Any], *, force: bool = False) -> None:
    """Perform ALSA pre-flight checks and cleanup."""
    capture_dev = config.get("capture", {}).get("device")
    playback_dev = config.get("playback", {}).get("device") or \
                   config.get("playback", {}).get("alsa_device")
    
    try:
        ensure_free(capture_dev, playback_dev, force=force)
    except ALSAError as e:
        if force:
            print(f"Error: ALSA devices not accessible even with --force: {e}", file=sys.stderr)
            sys.exit(1)
        else:
            print("Error: ALSA devices not accessible. Try --force to kill blocking processes.", file=sys.stderr)
            print(f"Details: {e}", file=sys.stderr)
            sys.exit(1)


def _synthesize_bytes(text: str, tts_cfg: dict[str, Any]) -> tuple[bytes, int, str]:
    """Synthesize text to audio bytes."""
    # Import here to use new wavutil
    from .audio.wavutil import decode_json_audio
    
    audio, sample_rate, fmt = synthesize(text, TTSConfig(**_filter_for_dataclass(tts_cfg, TTSConfig)))
    
    # Try to decode JSON audio if present
    json_result = decode_json_audio(audio)
    if json_result:
        raw_audio, json_sr, json_fmt = json_result
        return raw_audio, int(json_sr) if json_sr else sample_rate, json_fmt or fmt
        
    return audio, sample_rate, fmt


def _silence_logging_for_stdout() -> None:
    """Redirect logging to stderr for clean stdout output."""
    import logging as pylog
    
    for logger in (pylog.getLogger(), pylog.root):
        for handler in list(logger.handlers):
            try:
                handler.flush()
            except Exception:
                pass
            if hasattr(handler, "stream"):
                handler.stream = sys.stderr
                
    if not pylog.root.handlers:
        pylog.root.addHandler(pylog.StreamHandler(sys.stderr))
    pylog.disable(pylog.CRITICAL)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI Command Handlers
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_listen(args) -> None:
    """Continuous listening mode with ALSA pre-flight."""
    # VAD configuration for PTT mode
    if getattr(args, "hotword", None) == "ptt" and not getattr(args, "vad", None):
        args.vad = ["enabled=false"]
        
    config, _ = _configure(args)
    
    # ALSA pre-flight check
    _alsa_preflight(config, force=getattr(args, "force", False))
    
    try:
        from .svc_core import run_listen
        run_listen(config, args)
    finally:
        reset_streams()


def cmd_ptt(args) -> None:
    """Push-to-talk mode with ALSA pre-flight."""
    # Force PTT configuration
    args.hotword = "ptt"
    if not getattr(args, "vad", None):
        args.vad = ["enabled=false"]
        
    config, _ = _configure(args)
    
    # ALSA pre-flight check
    _alsa_preflight(config, force=getattr(args, "force", False))
    
    try:
        from .svc_core import run_listen
        run_listen(config, args)
    finally:
        reset_streams()


def cmd_once(args) -> None:
    """Single interaction mode with ALSA pre-flight."""
    # VAD configuration for PTT once
    if getattr(args, "hotword", None) == "ptt" and not getattr(args, "vad", None):
        args.vad = ["enabled=false"]
        
    config, _ = _configure(args)
    
    # ALSA pre-flight check
    _alsa_preflight(config, force=getattr(args, "force", False))
    
    try:
        from .svc_core import run_once
        run_once(config, args)
    finally:
        reset_streams()


def cmd_asr(args) -> None:
    """Transcribe audio file."""
    path = Path(args.file)
    if not path.exists():
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(1)
        
    with wave.open(str(path), "rb") as wf:
        sample_rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        
    config, _ = _configure(args)
    transcript = transcribe(frames, sample_rate, 
                          ASRConfig(**_filter_for_dataclass(config["asr"], ASRConfig)))
    print(transcript.text)


def cmd_tts(args) -> None:
    """Synthesize text to speech."""
    # Silence logging if outputting to stdout
    if not args.play and not sys.stdout.isatty():
        _silence_logging_for_stdout()
        
    config, _ = _configure(args)
    audio, sample_rate, fmt = _synthesize_bytes(args.text, config["tts"])
    
    if args.play:
        # ALSA pre-flight for playback
        _alsa_preflight(config, force=getattr(args, "force", False))
        
        try:
            play_bytes(audio, fmt, PlaybackConfig(**config["playback"]))
        finally:
            reset_streams()
    else:
        # Output to stdout
        wav_bytes = ensure_wav_format(audio, sample_rate, fmt)
        
        # Apply gain if specified
        try:
            gain = float(os.environ.get("VOICE_GAIN", "1.0"))
        except Exception:
            gain = 1.0
            
        if gain and abs(gain - 1.0) > 1e-6:
            wav_bytes = apply_gain_wav(wav_bytes, gain)
            
        sys.stdout.buffer.write(wav_bytes)


def cmd_diag(args) -> None:
    """Run diagnostics.""" 
    config, _ = _configure(args)
    
    # Basic system info
    print("Voice Assistant Diagnostics")
    print("=" * 40)
    
    # ALSA info
    from .audio.alsa import probe_devices
    print("ALSA Configuration:")
    devices_info = probe_devices()
    print(f"  Sound cards: {len(devices_info['cards'])}")
    print(f"  PCM devices: {len(devices_info['devices'])}")
    
    for alias, device in devices_info['aliases'].items():
        print(f"  {alias} -> {device}")
    
    # Backend info  
    capture_backend = config.get("capture", {}).get("backend", "alsa")
    tts_backend = config.get("tts", {}).get("backend", "openai")
    asr_backend = config.get("asr", {}).get("backend", "auto")
    
    print("\nBackend Configuration:")
    print(f"  Capture: {capture_backend}")
    print(f"  TTS: {tts_backend}")
    print(f"  ASR: {asr_backend}")
    
    # Mode detection
    try:
        from .svc_core import _mode_from_cfg
        mode = _mode_from_cfg(config)
    except Exception:
        mode = "file"  # fallback
        
    print(f"\nMode: {mode}")
    
    if mode == "realtime":
        endpoint = os.environ.get("OPENAI_REALTIME_ENDPOINT") or \
                  config.get("stream", {}).get("endpoint", "")
        masked_endpoint = endpoint.replace("model=", "model=***") if endpoint else "not configured"
        print(f"  Endpoint: {masked_endpoint}")
    
    # Playback info
    chosen_player = choose_player_command()
    print("\nPlayback:")
    print(f"  External player: {' '.join(chosen_player) if chosen_player else '<internal>'}")
    
    # Test ding if requested
    if getattr(args, "audio", False):
        print("\nTesting audio playback...")
        
        # ALSA pre-flight
        try:
            _alsa_preflight(config, force=getattr(args, "force", False))
            
            import time

            from .audio.playback import play_ding
            
            start = time.time()
            success = play_ding(PlaybackConfig(**config["playbook"]))
            elapsed_ms = int((time.time() - start) * 1000)
            
            print(f"  Ding playback: {'✓' if success else '✗'} ({elapsed_ms}ms)")
            
        except Exception as e:
            print(f"  Ding playback: ✗ ({e})")
        finally:
            reset_streams()


def cmd_free(args) -> None:
    """Free ALSA devices (new command)."""
    config, _ = _configure(args)
    
    print("Freeing ALSA devices...")
    try:
        result = _alsa_preflight(config, force=True)
        print("✓ ALSA devices are now free")
        if "processes_killed" in result and result["processes_killed"] > 0:
            print(f"  Killed {result['processes_killed']} blocking processes")
    except Exception as e:
        print(f"✗ Failed to free devices: {e}")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# Argument Parser
# ═══════════════════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Rider-Pi Voice Assistant (CLI-first)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s once --mode stream    # Single interaction via WebSocket
  %(prog)s ptt --force          # Push-to-talk with forced ALSA cleanup  
  %(prog)s listen --mode file   # Continuous mode with file processing
  %(prog)s diag --audio         # Run diagnostics with audio test
  %(prog)s free                 # Free ALSA devices
        """.strip()
    )
    
    # Global options
    parser.add_argument("--config", help="Path to config file", default=None)
    parser.add_argument("--lang", type=str, help="ASR language (pl|en|auto)", default=None)
    parser.add_argument("--force", action="store_true", help="Force free ALSA devices")
    
    sub = parser.add_subparsers(dest="cmd", help="Available commands")
    
    # listen command
    listen_cmd = sub.add_parser("listen", help="Continuous listening mode")
    listen_cmd.set_defaults(func=cmd_listen)
    listen_cmd.add_argument("--mode", choices=["stream", "file"], help="Processing mode")
    listen_cmd.add_argument("--hotword", choices=["on", "off", "ptt"], help="Hotword detection")
    _add_common_voice_args(listen_cmd)
    
    # ptt command
    ptt_cmd = sub.add_parser("ptt", help="Push-to-talk mode")
    ptt_cmd.set_defaults(func=cmd_ptt)
    ptt_cmd.add_argument("--mode", choices=["stream", "file"], help="Processing mode")
    _add_common_voice_args(ptt_cmd)
    
    # once command
    once_cmd = sub.add_parser("once", help="Single interaction mode")
    once_cmd.set_defaults(func=cmd_once)
    once_cmd.add_argument("--mode", choices=["stream", "file"], help="Processing mode")
    once_cmd.add_argument("--hotword", choices=["on", "off", "ptt"], help="Hotword detection")
    _add_common_voice_args(once_cmd)
    
    # asr command
    asr_cmd = sub.add_parser("asr", help="Transcribe audio file")
    asr_cmd.set_defaults(func=cmd_asr)
    asr_cmd.add_argument("--file", required=True, help="Audio file to transcribe")
    asr_cmd.add_argument("--asr", nargs="*", help="ASR overrides (key=value)")
    asr_cmd.add_argument("--log-level", help="Log level")
    
    # tts command
    tts_cmd = sub.add_parser("tts", help="Text to speech synthesis")
    tts_cmd.set_defaults(func=cmd_tts)
    tts_cmd.add_argument("--text", required=True, help="Text to synthesize")
    tts_cmd.add_argument("--play", action="store_true", help="Play audio instead of stdout")
    tts_cmd.add_argument("--tts", nargs="*", help="TTS overrides (key=value)")
    tts_cmd.add_argument("--playback", nargs="*", help="Playback overrides (key=value)")
    tts_cmd.add_argument("--log-level", help="Log level")
    
    # diag command
    diag_cmd = sub.add_parser("diag", help="Run diagnostics")
    diag_cmd.set_defaults(func=cmd_diag)
    diag_cmd.add_argument("--audio", action="store_true", help="Test audio playback")
    diag_cmd.add_argument("--stream", action="store_true", help="Test streaming connection")
    diag_cmd.add_argument("--no-network", action="store_true", help="Skip network tests")
    diag_cmd.add_argument("--mode", choices=["stream", "file"], help="Force mode detection")
    diag_cmd.add_argument("--log-level", help="Log level")
    
    # free command (new)
    free_cmd = sub.add_parser("free", help="Free ALSA devices")
    free_cmd.set_defaults(func=cmd_free)
    free_cmd.add_argument("--log-level", help="Log level")
    
    return parser


def _add_common_voice_args(parser: argparse.ArgumentParser) -> None:
    """Add common voice processing arguments."""
    parser.add_argument("--asr", nargs="*", help="ASR overrides (key=value)")
    parser.add_argument("--chat", nargs="*", help="Chat overrides (key=value)")
    parser.add_argument("--tts", nargs="*", help="TTS overrides (key=value)")
    parser.add_argument("--vad", nargs="*", help="VAD overrides (key=value)")
    parser.add_argument("--turn", nargs="*", help="Turn overrides (key=value)")
    parser.add_argument("--playback", nargs="*", help="Playback overrides (key=value)")
    parser.add_argument("--capture", nargs="*", help="Capture overrides (key=value)")
    parser.add_argument("--service", nargs="*", help="Service overrides (key=value)")
    parser.add_argument("--ding", choices=["on", "off"], help="Enable/disable ding sound")
    parser.add_argument("--save-audio", nargs="*", help="Audio saving overrides")
    parser.add_argument("--log-level", help="Log level")


def main(argv: Iterable[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 1
        
    try:
        args.func(args)
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())