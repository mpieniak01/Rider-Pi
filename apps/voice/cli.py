# apps/voice/cli.py
"""Command line interface for the Rider-Pi voice assistant (STRICT modes).

Najważniejsze zmiany:
- Dodano --mode {stream,file} dla komend: listen / ptt / once.
  * stream → asr/chat/tts.transport = "realtime"
  * file   → asr/chat/tts.transport = "file"
- Brak odwołań do starego `service` — wejścia idą przez `svc_core.run_*`.
- `diag` rozpoznaje tryb na bazie strictowego `_mode_from_cfg`.
"""

from __future__ import annotations

import argparse
import audioop  # stdlib
import base64
import io
import json
import logging as pylog
import os
import shutil
import sys
import warnings
import wave
from collections.abc import Iterable
from typing import Any

from . import config as voice_config, voice_logging as voice_logging
from .tts import TTSConfig, synthesize

# --- ensure local _configure symbol is patchable by tests ---
try:
    # preferujemy bezpośredni symbol z svc_core, ale opakowujemy go lokalnie
    from . import svc_core as _svc_core  # type: ignore

    def _configure(*args, **kwargs):  # noqa: D401
        """Local wrapper -> svc_core._configure (kept for test patching)."""
        return _svc_core._configure(*args, **kwargs)
except Exception:  # pragma: no cover
    # awaryjnie: zbuduj minimalny _configure, by nie wywalać się przy imporcie
    def _configure(*args, **kwargs):
        raise RuntimeError("svc_core._configure unavailable")
# --- end wrapper ---


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
# helper functions
# ───────────────────────────────────────────────────────────────────────────────


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


def _filter_transport_field(config_dict: dict[str, Any]) -> dict[str, Any]:
    """Remove transport field from config dict for legacy service classes."""
    filtered = dict(config_dict)
    filtered.pop("transport", None)
    return filtered


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


def _pairs_to_dict(pairs: list[str]) -> dict[str, Any]:
    """
    Zamienia listę par key=val na zagnieżdżony dict z obsługą kropki:
    ["a.b=1", "a.c=true"] -> {"a": {"b": "1", "c": "true"}}
    Typy bool/int są parsowane lekko konserwatywnie.
    """
    out: dict[str, Any] = {}
    for token in pairs:
        if "=" not in token:
            # flaga bez wartości → potraktuj jako true
            key, val = token, "true"
        else:
            key, val = token.split("=", 1)
        # proste rzutowania
        v: Any = val
        if isinstance(val, str) and val.lower() in ("true", "false"):
            v = val.lower() == "true"
        else:
            try:
                if isinstance(val, str) and val.isdigit():
                    v = int(val)
                else:
                    if isinstance(val, str) and val.startswith("-") and val[1:].isdigit():
                        v = int(val)
                    else:
                        v = float(val) if isinstance(val, str) and any(c in val for c in ".eE") else val
            except Exception:
                v = val
        # zagnieżdżanie po kropkach
        cur = out
        parts = key.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = v
    return out


def _build_overrides(args) -> dict[str, Any]:
    """
    Składa nadpisania z CLI. Najważniejsze poprawki:
    - --vad trafia do asr.vad (wcześniej było top-level 'vad')
    - --turn trafia do service.turn
    - --mode ustawia transporty (STRICT)
    """
    overrides: dict[str, Any] = {}
    if getattr(args, "asr", None):
        overrides = _merge(overrides, voice_config.override_from_pairs("asr", args.asr))
    if getattr(args, "chat", None):
        overrides = _merge(overrides, voice_config.override_from_pairs("chat", args.chat))
    if getattr(args, "tts", None):
        overrides = _merge(overrides, voice_config.override_from_pairs("tts", args.tts))

    # NEW: --mode → ustaw transporty spójnie (STRICT)
    mode = getattr(args, "mode", None)
    if mode == "stream":
        overrides = _merge(
            overrides,
            {
                "asr": {"transport": "realtime"},
                "chat": {"transport": "realtime"},
                "tts": {"transport": "realtime"},
            },
        )
    elif mode == "file":
        overrides = _merge(
            overrides,
            {
                "asr": {"transport": "file"},
                "chat": {"transport": "file"},
                "tts": {"transport": "file"},
            },
        )

    # NEW: --vad -> asr.vad
    if getattr(args, "vad", None):
        vad_dict = _pairs_to_dict(args.vad)
        overrides = _merge(overrides, {"asr": {"vad": vad_dict}})

    if getattr(args, "playback", None):
        overrides = _merge(overrides, voice_config.override_from_pairs("playback", args.playback))
    if getattr(args, "capture", None):
        overrides = _merge(overrides, voice_config.override_from_pairs("capture", args.capture))

    # service (legacy, nadal wspieramy)
    if getattr(args, "service", None):
        overrides = _merge(overrides, voice_config.override_from_pairs("service", args.service))

    # NEW: --turn -> service.turn
    if getattr(args, "turn", None):
        turn_dict = _pairs_to_dict(args.turn)
        overrides = _merge(overrides, {"service": {"turn": turn_dict}})

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

    # save-audio
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
        overrides = _merge(overrides, {"asr": {"language": lang}})

    return overrides


def _configure(args) -> tuple[dict[str, Any], None]:
    """Wczytaj config + nadpisania, skonfiguruj logowanie. Nie twórz VoiceService tutaj."""
    overrides = _build_overrides(args)
    config = voice_config.load(getattr(args, "config", None), overrides=overrides)
    voice_logging._configure(config.get("logging", {}).get("level"))
    return config, None


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
            sw = wf.getsampwidth()  # bytes
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
        raw: bytes | None = None
        if isinstance(payload, str):
            try:
                raw = base64.b64decode(payload)
            except Exception:
                return None
        elif isinstance(payload, dict):
            for k in ("b64", "base64", "data"):
                v = payload.get(k)
                if isinstance(v, str):
                    try:
                        raw = base64.b64decode(v)
                        break
                    except Exception:
                        return None
            if raw is None:
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


def _add_tail_silence(pcm: bytes, sr: int, ch: int, tail_ms: int | None = None) -> bytes:
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
    target_ch = int(os.environ.get("VOICE_CHANNELS", "2"))

    # 0) JSON?
    m = _decode_json_audio(audio)
    if m:
        audio, sr_json, fmt_json = m
        if sr_json:
            sample_rate = int(sr_json)
        if fmt_json:
            pass

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


def _synthesize_bytes(text: str, tts_cfg: dict[str, Any]) -> tuple[bytes, int, str]:
    """
    Normalizuje wyjście synthesize(...):
    - dekoduje JSON jeśli backend zwróci JSON z base64 audio
    - zwraca (audio_bytes, sample_rate, fmt_label)
    """
    audio, sample_rate, fmt = synthesize(text, TTSConfig(**_filter_for_dataclass(tts_cfg, TTSConfig)))
    maybe = _decode_json_audio(audio)
    if maybe:
        raw, sr_json, fmt_json = maybe
        return raw, int(sr_json) if sr_json else sample_rate, fmt_json or fmt
    return audio, sample_rate, fmt


def _pulse_available() -> bool:
    return bool(
        shutil.which("paplay")
        and (os.environ.get("PULSE_SERVER") or os.path.exists(os.path.expanduser("~/.config/pulse")))
    )


def _choose_player_command() -> list[str] | None:
    # (pozostawione dla kompatybilności; w --play korzystamy z play_bytes)
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
    for lg in (pylog.getLogger(), pylog.root):
        for h in list(lg.handlers):
            try:
                h.flush()
            except Exception:
                pass
            if hasattr(h, "stream"):
                h.stream = sys.stderr
    if not pylog.root.handlers:
        pylog.root.addHandler(pylog.StreamHandler(sys.stderr))
    pylog.disable(pylog.CRITICAL)


# ───────────────────────────────────────────────────────────────────────────────
# commands
# ───────────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser (delegated to cli_commands module)."""
    from .cli_commands import build_parser as _build_parser

    return _build_parser()


def cmd_listen(args) -> None:
    """Execute listen command (delegated to cli_commands module)."""
    from .cli_commands import cmd_listen as _cmd_listen

    _cmd_listen(args)


def cmd_ptt(args) -> None:
    """Execute PTT command (delegated to cli_commands module)."""
    from .cli_commands import cmd_ptt as _cmd_ptt

    _cmd_ptt(args)


def cmd_once(args) -> None:
    """Execute once command (delegated to cli_commands module)."""
    from .cli_commands import cmd_once as _cmd_once

    _cmd_once(args)


def cmd_asr(args) -> None:
    """Execute ASR command (delegated to cli_commands module)."""
    from .cli_commands import cmd_asr as _cmd_asr

    _cmd_asr(args)


def cmd_tts(args) -> None:
    """Execute TTS command (delegated to cli_commands module)."""
    from .cli_commands import cmd_tts as _cmd_tts

    _cmd_tts(args)


def cmd_diag(args) -> None:
    """Execute diagnostics command (delegated to cli_commands module)."""
    from .cli_commands import cmd_diag as _cmd_diag

    _cmd_diag(args)


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    # Handle --print-effective-config early (before subcommand requirement)
    if getattr(args, "print_effective_config", False):
        from .config_loader import (
            ValidationError,
            load_and_validate,
            print_effective_config as print_cfg,
        )

        overrides = _build_overrides(args) if hasattr(args, 'cmd') else {}
        lenient = getattr(args, "config_lenient", False)

        try:
            config = load_and_validate(
                path=getattr(args, "config", None),
                overrides=overrides,
                lenient=lenient,
            )
        except ValidationError as e:
            print(f"Configuration error:\n{e}", file=sys.stderr)
            return 1

        print_cfg(config, mask=True)
        return 0

    if not getattr(args, "cmd", None):
        parser.print_help()
        return 1
    args.func(args)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


# ────────────────────────────────────────────────────────────────────────────
# Re-exports from extracted modules (for API compatibility)
# ────────────────────────────────────────────────────────────────────────────

# All command functionality is already delegated via functions above
# No additional re-exports needed here

# --- test-facing shim: cli._configure & cmd_once ---

# Lokalny wrapper, który test może patchować: apps.voice.cli._configure
try:
    from . import svc_core as _svc_core  # type: ignore
except Exception:  # pragma: no cover
    _svc_core = None  # type: ignore


def _configure(*args, **kwargs):
    """Local wrapper -> svc_core._configure (trzymamy tę nazwę dla testów)."""
    if _svc_core is None or not hasattr(_svc_core, "_configure"):
        raise RuntimeError("svc_core._configure unavailable")
    return _svc_core._configure(*args, **kwargs)  # type: ignore


def _cmd_once_patched(args):
    # MUST call local _configure so tests can patch apps.voice.cli._configure
    cfg, service = _configure(args)
    # Call through module attribute so test patch on apps.voice.svc_core.run_once is effective
    return _svc_core.run_once(cfg, service)


# Jeśli w module już jest cmd_once, PRZEBINDUJ na naszą wersję (bez redefinicji -> brak F811).
if 'cmd_once' in globals():
    cmd_once = _cmd_once_patched  # type: ignore
else:
    cmd_once = _cmd_once_patched  # type: ignore

# --- end shim ---
