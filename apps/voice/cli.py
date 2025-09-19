# apps/voice/cli.py
"""Command line interface for the voice assistant."""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
import audioop  # stdlib
import warnings
import logging as pylog
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Optional, Tuple

from . import config as voice_config
from . import logging as voice_logging
from .asr import ASRConfig, transcribe
from .playback import PlaybackConfig, play_bytes, play_ding
from .service import VoiceService, setup_signals
from .tts import TTSConfig, synthesize


# ───────────────────────────────────────────────────────────────────────────────
# ostrzeżenia tylko na stderr + wyciszenie webrtcvad
# ───────────────────────────────────────────────────────────────────────────────

def _warn_to_stderr(message, category, filename, lineno, file=None, line=None):
    stream = file if file is not None else sys.stderr
    try:
        stream.write(f"{category.__name__}: {message}\n")
    except Exception:
        pass

warnings.showwarning = _warn_to_stderr
warnings.filterwarnings("ignore", category=UserWarning, module=r"webrtcvad")


# ───────────────────────────────────────────────────────────────────────────────
# helpers (merge, overrides)
# ───────────────────────────────────────────────────────────────────────────────

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
    if getattr(args, "capture", None):
        overrides = _merge(overrides, voice_config.override_from_pairs("capture", args.capture))
    if getattr(args, "service", None):
        overrides = _merge(overrides, voice_config.override_from_pairs("service", args.service))

    # hotword / ptt
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

    # ding
    ding = getattr(args, "ding", None)
    if ding:
        overrides = _merge(overrides, {"playback": {"ding": {"enabled": ding == "on"}}})

    # save-audio (krótki alias: --save-audio on recordings_dir=...)
    save_audio = getattr(args, "save_audio", None)
    if save_audio:
        values: dict[str, Any] = {}
        for token in save_audio:
            if token in ("on", "off"):
                values["save_audio"] = token == "on"
            elif "=" in token:
                key, val = token.split("=", 1)
                values[key.replace("-", "_")] = val
        overrides = _merge(overrides, {"service": values})

    # log level
    level = getattr(args, "log_level", None)
    if level:
        overrides = _merge(overrides, {"logging": {"level": level}})

    # globalny hint języka dla ASR
    lang = getattr(args, "lang", None)
    if lang:
        overrides = _merge(overrides, {"asr": {"lang": lang}})

    return overrides


def _configure(args) -> Tuple[dict[str, Any], VoiceService]:
    overrides = _build_overrides(args)
    config = voice_config.load(getattr(args, "config", None), overrides=overrides)
    voice_logging.configure(config.get("logging", {}).get("level"))
    service = VoiceService(config)
    return config, service


# ───────────────────────────────────────────────────────────────────────────────
# audio utils (JSON decode, WAV wrap, resample, gain)
# ───────────────────────────────────────────────────────────────────────────────

def _is_wav(b: bytes) -> bool:
    return len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WAVE"


def _read_wav_params(b: bytes):
    try:
        if not _is_wav(b):
            return None
        bio = io.BytesIO(b)
        with wave.open(bio, "rb") as wf:
            ch = wf.getnchannels()
            sw = wf.getsampwidth()   # bytes
            sr = wf.getframerate()
            pcm = wf.readframes(wf.getnframes())
        return pcm, sr, ch, sw
    except Exception:
        return None


def _wrap_wav(pcm: bytes, sample_rate: int, channels: int, sampwidth: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm)
    return buf.getvalue()


def _decode_json_audio(b: bytes):
    """
    Jeśli b wygląda na JSON → spróbuj wyciągnąć bajty audio.
    Obsługiwane pola: 'audio', 'data', 'bytes', 'b64', 'audio_b64'.
    Zwraca (audio_bytes, sr|None, fmt|None) lub None jeśli nie JSON.
    """
    try:
        txt = b.decode("utf-8", errors="ignore").strip()
        if not (txt.startswith("{") and txt.endswith("}")):
            return None
        obj = json.loads(txt)
        payload = None
        for k in ("audio", "data", "bytes", "b64", "audio_b64"):
            if k in obj:
                payload = obj[k]
                break
        if payload is None:
            return None
        if isinstance(payload, str):
            raw = base64.b64decode(payload)
        elif isinstance(payload, dict):
            for k in ("b64", "base64", "data"):
                if k in payload and isinstance(payload[k], str):
                    raw = base64.b64decode(payload[k])
                    break
            else:
                return None
        else:
            return None
        sr = obj.get("sr") or obj.get("sample_rate")
        fmt = obj.get("fmt") or obj.get("format")
        return raw, sr, fmt
    except Exception:
        return None


def _resample_to(pcm: bytes, in_sr: int, in_ch: int, target_sr: int, target_ch: int) -> bytes:
    out, _ = audioop.ratecv(pcm, 2, in_ch, in_sr, target_sr, None)
    if target_ch == 2 and in_ch == 1:
        out = audioop.tostereo(out, 2, 1, 1)
    elif target_ch == 1 and in_ch == 2:
        out = audioop.tomono(out, 2, 0.5, 0.5)
    return out


def _add_tail_silence(pcm: bytes, sr: int, ch: int, tail_ms: int = None) -> bytes:
    tail_ms = int(os.environ.get("VOICE_TAIL_MS", tail_ms or 120))
    tail_frames = int(sr * tail_ms / 1000.0) * ch
    return pcm + (b"\x00\x00" * tail_frames)


def _apply_gain_wav(wav_bytes: bytes, gain: float) -> bytes:
    got = _read_wav_params(wav_bytes)
    if not got or gain is None or abs(gain - 1.0) < 1e-6:
        return wav_bytes
    pcm, sr, ch, sw = got
    if sw != 2:
        return wav_bytes  # wspieramy tylko S16_LE
    try:
        pcm = audioop.mul(pcm, 2, float(gain))
    except Exception:
        return wav_bytes
    pcm = _add_tail_silence(pcm, sr, ch, None)
    return _wrap_wav(pcm, sr, ch, 2)


def _ensure_wav_bytes(audio: bytes, sample_rate: int, fmt: str) -> bytes:
    """
    Normalizuj wejście do prawidłowego WAV 48 kHz stereo.
    Obsługa: JSON->b64, już-WAV, RAW PCM16 mono (fallback).
    """
    target_rate = int(os.environ.get("VOICE_RATE", "48000"))
    target_ch   = int(os.environ.get("VOICE_CHANNELS", "2"))

    # 0) JSON?
    m = _decode_json_audio(audio)
    if m:
        audio, sr_json, fmt_json = m
        if sr_json:
            sample_rate = int(sr_json)
        if fmt_json:
            fmt = fmt_json

    # 1) jeśli to WAV
    got_wav = _read_wav_params(audio)
    if got_wav:
        pcm, in_sr, in_ch, in_sw = got_wav
        if in_sw == 2 and (in_sr != target_rate or in_ch != target_ch):
            pcm = _resample_to(pcm, in_sr, in_ch, target_rate, target_ch)
            in_sr, in_ch = target_rate, target_ch
        pcm = _add_tail_silence(pcm, in_sr, in_ch, None)
        return _wrap_wav(pcm, in_sr, in_ch, 2 if in_sw == 2 else in_sw)

    # 2) RAW PCM16 mono → przeskaluj
    out = _resample_to(audio, sample_rate, 1, target_rate, target_ch)
    out = _add_tail_silence(out, target_rate, target_ch, None)
    return _wrap_wav(out, target_rate, target_ch, 2)


def _synthesize_bytes(text: str, tts_cfg: dict[str, Any]) -> Tuple[bytes, int, str]:
    """
    Normalizuje wyjście synthesize(...):
    - dekoduje JSON jeśli backend zwróci JSON z base64 audio
    - zwraca (audio_bytes, sample_rate, fmt_label)
    """
    audio, sample_rate, fmt = synthesize(text, TTSConfig(**tts_cfg))
    # jeśli to JSON – dekoduj
    maybe = _decode_json_audio(audio)
    if maybe:
        raw, sr_json, fmt_json = maybe
        return raw, int(sr_json) if sr_json else sample_rate, fmt_json or fmt
    return audio, sample_rate, fmt


def _pulse_available() -> bool:
    return bool(shutil.which("paplay") and (os.environ.get("PULSE_SERVER") or
                                            os.path.exists(os.path.expanduser("~/.config/pulse"))))


def _choose_player_command() -> Optional[list[str]]:
    env_player = os.environ.get("VOICE_PLAYER")
    if env_player:
        return env_player.split()
    if _pulse_available():
        return ["paplay"]
    if shutil.which("aplay"):
        return ["aplay", "-q"]
    return None


# ───────────────────────────────────────────────────────────────────────────────
# log silencer – żeby stdout był czystym WAV przy redirekcie
# ───────────────────────────────────────────────────────────────────────────────

def _silence_logging_for_stdout() -> None:
    """Przekieruj wszystkie logi na stderr i wyłącz gadatliwość."""
    # przekieruj istniejące handlery loggerów na stderr
    for lg in (pylog.getLogger(), pylog.root):
        for h in list(lg.handlers):
            try:
                h.flush()
            except Exception:
                pass
            if hasattr(h, "stream"):
                h.stream = sys.stderr
    # jeśli nie ma żadnych handlerów – dodaj jeden na stderr
    if not pylog.root.handlers:
        pylog.root.addHandler(pylog.StreamHandler(sys.stderr))
    # kompletnie wycisz logowanie poniżej CRITICAL
    pylog.disable(pylog.CRITICAL)


# ───────────────────────────────────────────────────────────────────────────────
# commands
# ───────────────────────────────────────────────────────────────────────────────

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
    # jeśli zapisujemy na stdout (bez --play) i nie ma TTY → ucisz logi
    if not args.play and not sys.stdout.isatty():
        _silence_logging_for_stdout()

    config, _ = _configure(args)
    audio, sample_rate, fmt = _synthesize_bytes(args.text, config["tts"])
    wav_bytes = _ensure_wav_bytes(audio, sample_rate, fmt)

    # GAIN?
    try:
        g = float(os.environ.get("VOICE_GAIN", "1.0"))
    except Exception:
        g = 1.0
    if g and abs(g - 1.0) > 1e-6:
        wav_bytes = _apply_gain_wav(wav_bytes, g)

    if args.play:
        cmd = _choose_player_command()
        if cmd:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                f.write(wav_bytes)
                path = f.name
            try:
                print("playback.start:", " ".join(cmd + [path]))
                rc = subprocess.call(cmd + [path])
                print("playback.done: returncode=", rc)
            finally:
                try:
                    os.unlink(path)
                except Exception:
                    pass
        else:
            # fallback: wewnętrzny odtwarzacz (gdy brak aplay/paplay)
            play_bytes(wav_bytes, "wav", PlaybackConfig(**config["playback"]))
    else:
        # CZYSTY WAV na stdout
        sys.stdout.buffer.write(wav_bytes)


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
    chosen = _choose_player_command()
    print("Playback external:", " ".join(chosen) if chosen else "<internal>")
    print("Playing ding…")
    start = time.time()
    play_ding(PlaybackConfig(**config["playback"]))
    print("Ding triggered (async)")
    print("Elapsed ms:", int((time.time() - start) * 1000))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rider voice assistant")
    parser.add_argument("--config", help="Path to config file", default=None)
    parser.add_argument("--lang", type=str, help="ASR language hint (pl|en|auto)", default=None)

    sub = parser.add_subparsers(dest="cmd")

    listen = sub.add_parser("listen", help="Continuous mode")
    listen.set_defaults(func=cmd_listen)
    listen.add_argument("--hotword", choices=["on", "off", "ptt"], default=None)
    listen.add_argument("--asr", nargs="*")
    listen.add_argument("--tts", nargs="*")
    listen.add_argument("--vad", nargs="*")
    listen.add_argument("--playback", nargs="*")
    listen.add_argument("--capture", nargs="*")           # <— dodane
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
    ptt.add_argument("--capture", nargs="*")             # <— dodane
    ptt.add_argument("--ding", choices=["on", "off"], default=None)  # <— dodane
    ptt.add_argument("--service", nargs="*")
    ptt.add_argument("--save-audio", nargs="*")          # <— dodane (alias wygodny)
    ptt.add_argument("--log-level", default=None)

    once = sub.add_parser("once", help="Single cycle")
    once.set_defaults(func=cmd_once)
    once.add_argument("--hotword", choices=["on", "off", "ptt"], default=None)
    once.add_argument("--asr", nargs="*")
    once.add_argument("--tts", nargs="*")
    once.add_argument("--vad", nargs="*")                # <— dodane (symetria)
    once.add_argument("--playback", nargs="*")
    once.add_argument("--capture", nargs="*")            # <— dodane
    once.add_argument("--ding", choices=["on", "off"], default=None)  # <— dodane
    once.add_argument("--service", nargs="*")
    once.add_argument("--save-audio", nargs="*")         # <— dodane
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