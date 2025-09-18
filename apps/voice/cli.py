"""Command line interface for the voice assistant."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Any, Iterable

from . import config as voice_config
from . import logging as voice_logging
from .asr import ASRConfig, transcribe
from .playback import PlaybackConfig, play_bytes, play_ding
from .service import VoiceService, setup_signals
from .tts import TTSConfig, synthesize


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _merge(dict(base[key]), value)
        else:
            base[key] = value
    return base


def _build_overrides(args) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if getattr(args, "asr", None):
        overrides = _merge(overrides, voice_config.override_from_pairs("asr", args.asr))
    if getattr(args, "tts", None):
        overrides = _merge(overrides, voice_config.override_from_pairs("tts", args.tts))
    if getattr(args, "vad", None):
        overrides = _merge(overrides, voice_config.override_from_pairs("vad", args.vad))
    if getattr(args, "playback", None):
        overrides = _merge(overrides, voice_config.override_from_pairs("playback", args.playback))
    if getattr(args, "service", None):
        overrides = _merge(overrides, voice_config.override_from_pairs("service", args.service))
    hotword = getattr(args, "hotword", None)
    if hotword:
        if hotword == "off":
            overrides = _merge(overrides, {"hotword": {"enabled": False}})
        elif hotword == "ptt":
            overrides = _merge(overrides, {"hotword": {"enabled": True, "engine": "ptt"}})
        else:
            overrides = _merge(overrides, {"hotword": {"enabled": True}})
    if getattr(args, "ptt", False):
        overrides = _merge(overrides, {"hotword": {"enabled": True, "engine": "ptt"}})
    ding = getattr(args, "ding", None)
    if ding:
        overrides = _merge(overrides, {"playback": {"ding": {"enabled": ding == "on"}}})
    save_audio = getattr(args, "save_audio", None)
    if save_audio:
        values = {}
        for token in save_audio:
            if token in ("on", "off"):
                values["save_audio"] = token == "on"
            elif "=" in token:
                key, val = token.split("=", 1)
                values[key.replace("-", "_")] = val
        overrides = _merge(overrides, {"service": values})
    level = getattr(args, "log_level", None)
    if level:
        overrides = _merge(overrides, {"logging": {"level": level}})
    return overrides


def _configure(args) -> tuple[dict[str, Any], VoiceService]:
    overrides = _build_overrides(args)
    config = voice_config.load(getattr(args, "config", None), overrides=overrides)
    voice_logging.configure(config.get("logging", {}).get("level"))
    service = VoiceService(config)
    return config, service


def cmd_listen(args) -> None:
    _, service = _configure(args)
    setup_signals(service)
    service.listen()


def cmd_ptt(args) -> None:
    args.hotword = "ptt"
    cmd_listen(args)


def cmd_once(args) -> None:
    _, service = _configure(args)
    setup_signals(service)
    result = service.once()
    if result:
        print(result.transcript.text)


def cmd_asr(args) -> None:
    path = Path(args.file)
    with wave.open(str(path), "rb") as wf:
        sample_rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    overrides = _build_overrides(args)
    config = voice_config.load(args.config, overrides=overrides)
    voice_logging.configure(config.get("logging", {}).get("level"))
    transcript = transcribe(frames, sample_rate, ASRConfig(**config["asr"]))
    print(transcript.text)


def cmd_tts(args) -> None:
    config, _ = _configure(args)
    audio, sample_rate, fmt = synthesize(args.text, TTSConfig(**config["tts"]))
    if args.play:
        play_bytes(audio, fmt, PlaybackConfig(**config["playback"]))
    else:
        sys.stdout.buffer.write(audio)


def cmd_diag(args) -> None:
    config, _ = _configure(args)
    capture_backend = config["capture"]["backend"]
    print("Capture backend:", capture_backend)
    if capture_backend == "alsa" and shutil.which("arecord"):
        print("== arecord -l ==")
        subprocess.run(["arecord", "-l"], check=False)
    if shutil.which("pactl"):
        print("== pactl list short sources ==")
        subprocess.run(["pactl", "list", "short", "sources"], check=False)
    print("TTS backend:", config["tts"]["backend"])
    print("ASR backend:", config["asr"]["backend"])
    print("Playing ding…")
    start = time.time()
    play_ding(PlaybackConfig(**config["playback"]))
    print("Ding triggered (async)")
    print("Elapsed ms:", int((time.time() - start) * 1000))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rider voice assistant")
    parser.add_argument("--config", help="Path to config file", default=None)
    sub = parser.add_subparsers(dest="cmd")

    listen = sub.add_parser("listen", help="Continuous mode")
    listen.set_defaults(func=cmd_listen)
    listen.add_argument("--hotword", choices=["on", "off", "ptt"], default=None)
    listen.add_argument("--asr", nargs="*")
    listen.add_argument("--tts", nargs="*")
    listen.add_argument("--vad", nargs="*")
    listen.add_argument("--playback", nargs="*")
    listen.add_argument("--service", nargs="*")
    listen.add_argument("--ding", choices=["on", "off"], default=None)
    listen.add_argument("--save-audio", nargs="*")
    listen.add_argument("--log-level", default=None)

    ptt = sub.add_parser("ptt", help="Push-to-talk mode")
    ptt.set_defaults(func=cmd_ptt)
    ptt.add_argument("--asr", nargs="*")
    ptt.add_argument("--tts", nargs="*")
    ptt.add_argument("--vad", nargs="*")
    ptt.add_argument("--playback", nargs="*")
    ptt.add_argument("--service", nargs="*")
    ptt.add_argument("--log-level", default=None)

    once = sub.add_parser("once", help="Single cycle")
    once.set_defaults(func=cmd_once)
    once.add_argument("--hotword", choices=["on", "off", "ptt"], default=None)
    once.add_argument("--asr", nargs="*")
    once.add_argument("--tts", nargs="*")
    once.add_argument("--log-level", default=None)

    asr_cmd = sub.add_parser("asr", help="Transcribe file")
    asr_cmd.set_defaults(func=cmd_asr)
    asr_cmd.add_argument("--file", required=True)
    asr_cmd.add_argument("--asr", nargs="*")
    asr_cmd.add_argument("--log-level", default=None)

    tts_cmd = sub.add_parser("tts", help="Synthesize text")
    tts_cmd.set_defaults(func=cmd_tts)
    tts_cmd.add_argument("--text", required=True)
    tts_cmd.add_argument("--play", action="store_true")
    tts_cmd.add_argument("--tts", nargs="*")
    tts_cmd.add_argument("--playback", nargs="*")
    tts_cmd.add_argument("--log-level", default=None)

    diag = sub.add_parser("diag", help="Diagnostics")
    diag.set_defaults(func=cmd_diag)
    diag.add_argument("--log-level", default=None)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 1
    args.func(args)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
