# apps/voice/web.py
from __future__ import annotations

import argparse
import audioop
import base64
import io
import math
import os
import shutil
import struct
import subprocess
import tempfile
import wave

from flask import Flask, Response, jsonify, request

# ───────────────────────────────────────────────────────────────────────────────
# Instancja aplikacji + polyfill dla Flask < 2.0
# ───────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)

if not hasattr(app, "get"):

    def _route_get(path, **kw):
        return app.route(path, methods=["GET"], **kw)

    def _route_post(path, **kw):
        return app.route(path, methods=["POST"], **kw)

    app.get = _route_get  # type: ignore[attr-defined]
    app.post = _route_post  # type: ignore[attr-defined]

# ───────────────────────────────────────────────────────────────────────────────
# Opcjonalne lokalne backendy (Piper / Vosk) – importy „best-effort”
# ───────────────────────────────────────────────────────────────────────────────

_PIPER_OK = False
_VOSK_OK = False

# Preferujemy projektowy wrapper kompatybilnościowy:
# apps.voice.piper_compat.PiperVoice z metodą klasową .load(model_path)
try:
    from apps.voice.piper_compat import PiperVoice  # type: ignore

    _PIPER_OK = True
except Exception:
    _PIPER_OK = False

try:
    from vosk import KaldiRecognizer, Model  # type: ignore  # pip install vosk

    _VOSK_OK = True
except Exception:
    _VOSK_OK = False

# Ścieżki do modeli – można nadpisać ENV:
# Preferencje:
#   1) PIPER_MODEL (pełna ścieżka do .onnx)
#   2) PIPER_MODEL_DIR + PIPER_VOICE (np. dir + "pl_PL-mls-medium.onnx")
#   3) fallback: <PIPER_MODEL_DIR>/pl_PL-mls-medium.onnx
PIPER_MODEL = os.getenv("PIPER_MODEL", "").strip()
PIPER_MODEL_DIR = os.getenv("PIPER_MODEL_DIR", "/home/pi/robot/models/piper").rstrip("/")
PIPER_VOICE = os.getenv("PIPER_VOICE", "pl_PL-mls-medium.onnx").strip()

# Vosk
VOSK_MODEL = os.getenv("VOSK_MODEL", "/home/pi/robot/models/vosk/vosk-model-small-pl-0.22")

# Cache instancji lokalnych backendów
_local_piper_voice = None
_local_vosk_model = None


def _resolve_piper_model_path(payload_voice: str | None = None) -> str:
    """Zwraca pełną ścieżkę do modelu Piper."""
    # 1) jawnie przez PIPER_MODEL
    if PIPER_MODEL:
        return PIPER_MODEL
    # 2) voice z payloadu (nazwa pliku) + DIR
    if payload_voice:
        return f"{PIPER_MODEL_DIR}/{payload_voice}"
    # 3) ENV voice + DIR
    if PIPER_VOICE:
        return f"{PIPER_MODEL_DIR}/{PIPER_VOICE}"
    # 4) fallback
    return f"{PIPER_MODEL_DIR}/pl_PL-mls-medium.onnx"


def _get_local_piper_voice(model_path: str | None = None):
    """
    Zwraca PiperVoice (singleton) lub podnosi RuntimeError, gdy brak modułu/modelu.
    Używa PiperVoice.load(model_path).
    """
    if not _PIPER_OK:
        raise RuntimeError("piper module not available (apps.voice.piper_compat.PiperVoice)")
    global _local_piper_voice
    if _local_piper_voice is None:
        model = model_path or _resolve_piper_model_path()
        if not os.path.isfile(model):
            raise RuntimeError(f"Piper model not found: {model}")
        _local_piper_voice = PiperVoice.load(model)
    return _local_piper_voice


def _get_local_vosk_model():
    """Zwraca vosk.Model (singleton) lub podnosi RuntimeError, gdy brak modułu/modelu."""
    if not _VOSK_OK:
        raise RuntimeError("vosk module not available (pip install vosk)")
    global _local_vosk_model
    if _local_vosk_model is None:
        if not os.path.isdir(VOSK_MODEL):
            raise RuntimeError(f"Vosk model not found dir: {VOSK_MODEL}")
        _local_vosk_model = Model(VOSK_MODEL)
    return _local_vosk_model


# ───────────────────────────────────────────────────────────────────────────────
# Pomocniki audio (minimalne; kompatybilne z Py3.9)
# ───────────────────────────────────────────────────────────────────────────────


def _is_wav(b: bytes) -> bool:
    return len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WAVE"


def _read_wav_params(b: bytes):
    """Jeśli b to WAV → (pcm, sr, ch, sw). Inaczej None."""
    try:
        if not _is_wav(b):
            return None
        bio = io.BytesIO(b)
        with wave.open(bio, "rb") as wf:
            ch = wf.getnchannels()
            sw = wf.getsampwidth()
            sr = wf.getframerate()
            pcm = wf.readframes(wf.getnframes())
        return pcm, sr, ch, sw
    except Exception:
        return None


def _wrap_wav(pcm: bytes, sr: int, ch: int, sw: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(ch)
        wf.setsampwidth(sw)
        wf.setframerate(int(sr))
        wf.writeframes(pcm)
    return buf.getvalue()


def _is_mp3(b: bytes) -> bool:
    return len(b) >= 3 and (b[:3] == b"ID3" or (b[0] == 0xFF and (b[1] & 0xE0) == 0xE0))


def _is_ogg(b: bytes) -> bool:
    return b.startswith(b"OggS")


def _decode_with_tool_to_wav(audio: bytes) -> bytes | None:
    """
    Dekoduj MP3/OGG do WAV narzędziem systemowym (mpg123 lub ffmpeg).
    Zwraca bajty WAV lub None.
    """
    if shutil.which("mpg123"):
        try:
            p = subprocess.run(
                ["mpg123", "-q", "-w", "-", "-"],
                input=audio,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            if _is_wav(p.stdout):
                return p.stdout
        except Exception:
            pass
    if shutil.which("ffmpeg"):
        try:
            p = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    "pipe:0",
                    "-f",
                    "wav",
                    "pipe:1",
                ],
                input=audio,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            if _is_wav(p.stdout):
                return p.stdout
        except Exception:
            pass
    return None


# ── audio shaping: fade & tail ────────────────────────────────────────────────


def _apply_fade(pcm: bytes, sr: int, ch: int, sampwidth: int = 2, fade_in_ms: int = 15, fade_out_ms: int = 20) -> bytes:
    """Łagodny fade-in/out na PCM16 (eliminuje „pyknięcia”)."""
    if sampwidth != 2 or not pcm:
        return pcm
    frame_len = sampwidth * ch
    n = len(pcm) // (sampwidth * ch)
    if n <= 0:
        return pcm
    fi = max(0, int(sr * fade_in_ms / 1000))
    fo = max(0, int(sr * fade_out_ms / 1000))
    fi = min(fi, n)
    fo = min(fo, n)
    out = bytearray(len(pcm))

    # ramp-in
    for i in range(fi):
        gain = i / fi if fi else 1.0
        for c in range(ch):
            s = struct.unpack_from("<h", pcm, (i * ch + c) * 2)[0]
            struct.pack_into("<h", out, (i * ch + c) * 2, int(s * gain))

    # środek bez zmian
    start_mid = fi
    end_mid = n - fo
    if end_mid > start_mid:
        out[start_mid * frame_len : end_mid * frame_len] = pcm[start_mid * frame_len : end_mid * frame_len]

    # ramp-out
    for i in range(n - fo, n):
        gain = (n - i) / fo if fo else 1.0
        for c in range(ch):
            s = struct.unpack_from("<h", pcm, (i * ch + c) * 2)[0]
            struct.pack_into("<h", out, (i * ch + c) * 2, int(s * gain))

    return bytes(out)


def _append_tail(pcm: bytes, sr: int, ch: int, ms: int) -> bytes:
    frames = int(sr * ms / 1000) * ch
    if frames > 0:
        pcm += b"\x00\x00" * frames
    return pcm


def _maybe_gain(pcm: bytes, gain: float) -> bytes:
    if gain == 1.0:
        return pcm
    g = max(0.1, min(gain, 3.0))
    return audioop.mul(pcm, 2, g)


# ── resampling ────────────────────────────────────────────────────────────────


def _resample_to(pcm: bytes, in_sr: int, in_ch: int, target_sr: int, target_ch: int) -> bytes:
    out, _ = audioop.ratecv(pcm, 2, in_ch, in_sr, target_sr, None)
    if target_ch == 2 and in_ch == 1:
        out = audioop.tostereo(out, 2, 1, 1)
    elif target_ch == 1 and in_ch == 2:
        out = audioop.tomono(out, 2, 0.5, 0.5)

    fade_in_ms = int(os.environ.get("VOICE_FADE_IN_MS", "15"))
    fade_out_ms = int(os.environ.get("VOICE_FADE_OUT_MS", "20"))
    tail_ms = int(os.environ.get("VOICE_TAIL_MS", "300"))
    gain = float(os.environ.get("VOICE_GAIN", "1.0"))

    out = _apply_fade(out, target_sr, target_ch, 2, fade_in_ms, fade_out_ms)
    out = _append_tail(out, target_sr, target_ch, tail_ms)
    out = _maybe_gain(out, gain)
    return out


def _ensure_wav_bytes(audio: bytes, sample_rate: int | None, fmt: str | None) -> bytes | None:
    """
    Upewnij się, że zwrócimy poprawny WAV @ VOICE_RATE/VOICE_CHANNELS.
    - przyjmujemy: WAV, MP3/OGG, lub (awaryjnie) RAW PCM16 mono @ sample_rate
    """
    target_sr = int(os.environ.get("VOICE_RATE", "48000"))
    target_ch = int(os.environ.get("VOICE_CHANNELS", "2"))

    fade_in_ms = int(os.environ.get("VOICE_FADE_IN_MS", "15"))
    fade_out_ms = int(os.environ.get("VOICE_FADE_OUT_MS", "20"))
    tail_ms = int(os.environ.get("VOICE_TAIL_MS", "300"))
    gain = float(os.environ.get("VOICE_GAIN", "1.0"))

    # 1) WAV
    got = _read_wav_params(audio)
    if got:
        pcm, in_sr, in_ch, in_sw = got
        if in_sw == 2 and (in_sr != target_sr or in_ch != target_ch):
            pcm = _resample_to(pcm, in_sr, in_ch, target_sr, target_ch)
            in_sr, in_ch = target_sr, target_ch
        else:
            if in_sw == 2:
                pcm = _apply_fade(pcm, in_sr, in_ch, 2, fade_in_ms, fade_out_ms)
                pcm = _append_tail(pcm, in_sr, in_ch, tail_ms)
                pcm = _maybe_gain(pcm, gain)
        return _wrap_wav(pcm, in_sr, in_ch, 2 if in_sw == 2 else in_sw)

    # 2) MP3/OGG
    if _is_mp3(audio) or _is_ogg(audio) or (fmt or "").lower() in ("mp3", "mpeg", "audio/mpeg", "ogg"):
        wav = _decode_with_tool_to_wav(audio)
        if wav and _is_wav(wav):
            got2 = _read_wav_params(wav)
            if got2:
                pcm, in_sr, in_ch, in_sw = got2
                if in_sw == 2 and (in_sr != target_sr or in_ch != target_ch):
                    pcm = _resample_to(pcm, in_sr, in_ch, target_sr, target_ch)
                    in_sr, in_ch = target_sr, target_ch
                else:
                    if in_sw == 2:
                        pcm = _apply_fade(pcm, in_sr, in_ch, 2, fade_in_ms, fade_out_ms)
                        pcm = _append_tail(pcm, in_sr, in_ch, tail_ms)
                        pcm = _maybe_gain(pcm, gain)
                return _wrap_wav(pcm, in_sr, in_ch, 2 if in_sw == 2 else in_sw)
        return None

    # 3) RAW PCM16 mono
    try:
        sr = int(sample_rate or 24000)
        pcm = _resample_to(audio, sr, 1, target_sr, target_ch)
        return _wrap_wav(pcm, target_sr, target_ch, 2)
    except Exception:
        return None


# ───────────────────────────────────────────────────────────────────────────────
# Piper: ujednolicony helper generujący WAV niezależnie od wariantu API
# ───────────────────────────────────────────────────────────────────────────────


def _piper_synthesize_wav_bytes(voice, text: str, model_path: str | None = None) -> tuple[bytes, int | None]:
    """
    Zwraca (wav_bytes, sample_rate|None). Obsługuje:
    - synthesize_wav_bytes(text) -> bytes lub (bytes, sr)
    - *to_file metody: synthesize_wav/synthesize_to_wav/save_wav/synthesize_to_file
    - synthesize(..., wav_file=...) (kwargs lub pozycyjnie)
    - tts()/synthesize() zwracające PCM → pakowanie do WAV
    - Fallback: CLI `piper` → WAV na stdout (wymaga zainstalowanego binarnego piper)
    """
    # 0) gotowe WAV bytes
    if hasattr(voice, "synthesize_wav_bytes"):
        out = voice.synthesize_wav_bytes(text)  # type: ignore[attr-defined]
        if isinstance(out, tuple):
            wav_bytes, sr = out
        else:
            wav_bytes, sr = out, None
        return wav_bytes, sr

    # 1) metody zapisujące do pliku
    file_methods = ["synthesize_wav", "synthesize_to_wav", "save_wav", "synthesize_to_file"]
    for m in file_methods:
        if hasattr(voice, m):
            fn = getattr(voice, m)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                try:
                    fn(text, tmp_path)  # (text, wav_file)
                except TypeError:
                    try:
                        fn(wav_file=tmp_path, text=text)  # kwargs
                    except TypeError:
                        fn(text=text, wav_file=tmp_path)
                with open(tmp_path, "rb") as f:
                    wav_bytes = f.read()
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
                if _is_wav(wav_bytes):
                    got = _read_wav_params(wav_bytes)
                    return wav_bytes, (got[1] if got else None)
            except Exception:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
                continue

    # 2) synthesize(..., wav_file=...) — częsty wariant w starszych buildach
    if hasattr(voice, "synthesize"):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            try:
                voice.synthesize(text, tmp_path)  # (text, wav_file)
            except TypeError:
                try:
                    voice.synthesize(wav_file=tmp_path, text=text)  # kwargs
                except TypeError:
                    voice.synthesize(text=text, wav_file=tmp_path)
            with open(tmp_path, "rb") as f:
                wav_bytes = f.read()
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            if _is_wav(wav_bytes):
                got = _read_wav_params(wav_bytes)
                return wav_bytes, (got[1] if got else None)
        except Exception:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            # przejdź do PCM/CLI

    # 3) fallback: synthesize()/tts() → PCM
    pcm, sr = None, None
    if hasattr(voice, "synthesize"):
        try:
            pcm, sr = voice.synthesize(text)  # type: ignore[attr-defined]
        except TypeError:
            pass
    if pcm is None and hasattr(voice, "tts"):
        pcm, sr = voice.tts(text)  # type: ignore[attr-defined]

    if pcm is not None:
        if hasattr(pcm, "dtype"):
            import numpy as _np

            if str(pcm.dtype) != "int16":
                pcm = (_np.clip(pcm, -1.0, 1.0) * 32767.0).astype("int16")
            pcm_bytes = pcm.tobytes()
        elif isinstance(pcm, bytes):
            pcm_bytes = pcm
        else:
            import numpy as _np

            arr = _np.array(list(pcm), dtype="float32")
            arr = (_np.clip(arr, -1.0, 1.0) * 32767.0).astype("int16")
            pcm_bytes = arr.tobytes()

        target_sr = int(os.environ.get("VOICE_RATE", "48000"))
        target_ch = int(os.environ.get("VOICE_CHANNELS", "2"))
        ch = 1
        wav_bytes = _wrap_wav(
            _resample_to(pcm_bytes, int(sr or 22050), ch, target_sr, target_ch),
            target_sr,
            target_ch,
            2,
        )
        return wav_bytes, target_sr

    # 4) OSTATECZNY fallback: CLI `piper` (jeśli dostępny)
    if shutil.which("piper") and (model_path or os.getenv("PIPER_MODEL") or os.getenv("PIPER_VOICE")):
        mp = model_path or os.getenv("PIPER_MODEL")
        if not mp:
            mp = (
                f'{os.getenv("PIPER_MODEL_DIR", "/home/pi/robot/models/piper").rstrip("/")}/'
                f'{os.getenv("PIPER_VOICE", "pl_PL-mls-medium.onnx")}'
            )
        try:
            # `piper -m <model> -f -` → WAV na stdout, tekst na stdin
            p = subprocess.run(
                ["piper", "-m", mp, "-f", "-"],
                input=(text + "\n").encode("utf-8"),
                capture_output=True,
                check=True,
            )
            if _is_wav(p.stdout):
                got = _read_wav_params(p.stdout)
                return p.stdout, (got[1] if got else None)
            raise RuntimeError(f"piper CLI returned non-WAV (stderr={p.stderr.decode('utf-8', 'ignore')[:200]})")
        except Exception as e:
            raise RuntimeError(f"piper CLI failed: {e}") from e

    raise RuntimeError("Piper synth failed: no supported method")


# ───────────────────────────────────────────────────────────────────────────────
# Trasy
# ───────────────────────────────────────────────────────────────────────────────


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.get("/api/tts-test")
def api_tts_test():
    """Pół sekundy tonu 1 kHz jako pewny WAV — do diagnostyki."""
    sr = int(os.environ.get("VOICE_RATE", "48000"))
    ch = int(os.environ.get("VOICE_CHANNELS", "2"))
    dur = 0.5
    n = int(sr * dur)
    pcm = bytearray()
    for i in range(n):
        s = int(0.20 * 32767 * math.sin(2 * math.pi * 1000 * (i / sr)))
        if ch == 1:
            pcm += struct.pack("<h", s)
        else:
            pcm += struct.pack("<hh", s, s)
    pcm = _apply_fade(
        bytes(pcm),
        sr,
        ch,
        2,
        int(os.environ.get("VOICE_FADE_IN_MS", "15")),
        int(os.environ.get("VOICE_FADE_OUT_MS", "20")),
    )
    pcm = _append_tail(pcm, sr, ch, int(os.environ.get("VOICE_TAIL_MS", "300")))
    pcm = _maybe_gain(pcm, float(os.environ.get("VOICE_GAIN", "1.0")))
    wav = _wrap_wav(pcm, sr, ch, 2)
    return Response(wav, mimetype="audio/wav", headers={"Content-Disposition": "inline; filename=test.wav"})


@app.post("/api/tts")
def api_tts():
    """
    JSON in: { "text": "...", "backend|provider": "openai|gemini|local|piper", "format": "wav|mp3", "voice": "..." }
    Domyślnie zwraca **audio/wav** (surowe bajty).
    Dodaj ?b64=1 aby dostać JSON: { audio_b64: "..." }.
    """
    try:
        payload = request.get_json(force=True, silent=True) or {}
        text = (payload.get("text") or "").strip()
        if not text:
            return jsonify({"status": "error", "error": "missing text"}), 400

        backend = (payload.get("backend") or payload.get("provider") or payload.get("tts") or "").strip().lower()

        # 1) Kanał lokalny (Piper)
        if backend in ("local", "piper"):
            if not _PIPER_OK:
                return jsonify({"status": "error", "error": "piper module not available"}), 500
            try:
                voice_name = payload.get("voice")
                model_path = _resolve_piper_model_path(voice_name if isinstance(voice_name, str) else None)
                voice = _get_local_piper_voice(model_path)

                wav_bytes, sr = _piper_synthesize_wav_bytes(voice, text, model_path)
                wav = _ensure_wav_bytes(wav_bytes, sr, "wav")
            except Exception as e:
                return jsonify({"status": "error", "error": f"local piper failed: {e}"}), 500

            if not wav or not _is_wav(wav):
                return jsonify({"status": "error", "error": "piper produced no WAV"}), 500

            if request.args.get("b64") == "1":
                b64 = base64.b64encode(wav).decode("ascii")
                return jsonify({"status": "ok", "fmt": "wav", "audio_b64": b64})
            return Response(wav, mimetype="audio/wav", headers={"Content-Disposition": "inline; filename=tts.wav"})

        # 2) Pozostałe kanały – OpenAI/Gemini
        from . import config as voice_config
        from .tts import TTSConfig, synthesize

        overrides = {}
        tts_pairs = []
        for k in ("backend", "provider", "format", "voice", "model"):
            if k in payload:
                key = "backend" if k in ("backend", "provider") else k
                tts_pairs.append(f"{key}={payload[k]}")
        if tts_pairs:
            overrides = {"tts": voice_config.override_from_pairs("tts", tts_pairs)["tts"]}

        cfg = voice_config.load(None, overrides=overrides)

        cfg_backend = str(cfg.get("tts", {}).get("backend", "")).lower()
        if cfg_backend in ("local", "piper"):
            if not _PIPER_OK:
                return jsonify({"status": "error", "error": "piper module not available"}), 500
            try:
                model_path = _resolve_piper_model_path()
                voice = _get_local_piper_voice(model_path)
                wav_bytes, sr = _piper_synthesize_wav_bytes(voice, text, model_path)
                wav = _ensure_wav_bytes(wav_bytes, sr, "wav")
            except Exception as e:
                return jsonify({"status": "error", "error": f"local piper failed: {e}"}), 500

            if not wav or not _is_wav(wav):
                return jsonify({"status": "error", "error": "piper produced no WAV"}), 500

            if request.args.get("b64") == "1":
                b64 = base64.b64encode(wav).decode("ascii")
                return jsonify({"status": "ok", "fmt": "wav", "audio_b64": b64})
            return Response(wav, mimetype="audio/wav", headers={"Content-Disposition": "inline; filename=tts.wav"})

        # W przeciwnym razie – chmurowy synth
        audio, sr, fmt = synthesize(text, TTSConfig(**cfg["tts"]))
        wav = _ensure_wav_bytes(audio, sr, fmt)
        if not wav or not _is_wav(wav):
            return jsonify({"status": "error", "error": "synthesis produced no WAV"}), 500

        if request.args.get("b64") == "1":
            b64 = base64.b64encode(wav).decode("ascii")
            return jsonify({"status": "ok", "fmt": "wav", "audio_b64": b64})

        return Response(
            wav,
            mimetype="audio/wav",
            headers={"Content-Disposition": "inline; filename=tts.wav"},
        )

    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ───────────────────────────────────────────────────────────────────────────────
# Lokalny ASR (Vosk) – przyjmuje WAV (lub MP3/OGG), zwraca JSON
# ───────────────────────────────────────────────────────────────────────────────


@app.post("/api/asr")
def api_asr():
    """
    POST audio (preferowane Content-Type: audio/wav) lub multipart 'file'.
    Zwraca JSON: { ok: true, text: "..." }
    """
    try:
        if not _VOSK_OK:
            return jsonify({"ok": False, "error": "vosk module not available"}), 500

        audio_bytes: bytes | None = None
        ctype = (request.headers.get("Content-Type") or "").lower()

        if "multipart" in ctype and request.files:
            f = request.files.get("file")
            if f:
                audio_bytes = f.read()
        if audio_bytes is None:
            audio_bytes = request.get_data(cache=False, as_text=False) or None

        if not audio_bytes:
            return jsonify({"ok": False, "error": "no audio data"}), 400

        wav = None
        if _is_wav(audio_bytes):
            wav = audio_bytes
        else:
            if _is_mp3(audio_bytes) or _is_ogg(audio_bytes) or "mpeg" in ctype or "ogg" in ctype:
                wav = _decode_with_tool_to_wav(audio_bytes)
            if wav is None and "application/octet-stream" in ctype:
                try:
                    pcm = audio_bytes
                    wav = _wrap_wav(pcm, 16000, 1, 2)
                except Exception:
                    wav = None

        if not wav or not _is_wav(wav):
            return jsonify({"ok": False, "error": "unsupported or invalid audio"}), 400

        got = _read_wav_params(wav)
        if not got:
            return jsonify({"ok": False, "error": "invalid wav"}), 400
        pcm, in_sr, in_ch, in_sw = got
        if in_sw != 2:
            return jsonify({"ok": False, "error": "expected 16-bit PCM"}), 400

        target_sr = 16000
        target_ch = 1
        if in_sr != target_sr or in_ch != target_ch:
            pcm = _resample_to(pcm, in_sr, in_ch, target_sr, target_ch)

        model = _get_local_vosk_model()
        rec = KaldiRecognizer(model, target_sr)
        rec.AcceptWaveform(pcm)
        import json as _json

        try:
            data = _json.loads(rec.FinalResult() or "{}")
        except Exception:
            data = {"text": ""}

        return jsonify({"ok": True, "text": (data.get("text") or "").strip()}), 200

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ───────────────────────────────────────────────────────────────────────────────
# Uruchamianie modułem: python -m apps.voice.web --bind 0.0.0.0:8092
# ───────────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="127.0.0.1:8092", help="host:port")
    args = parser.parse_args()
    host, port = args.bind.split(":")
    app.run(host=host, port=int(port))


if __name__ == "__main__":
    main()
