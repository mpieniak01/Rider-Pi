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
try:
    import piper  # type: ignore  # pip install piper-tts

    _PIPER_OK = True
except Exception:
    _PIPER_OK = False

try:
    from vosk import KaldiRecognizer, Model  # type: ignore  # pip install vosk

    _VOSK_OK = True
except Exception:
    _VOSK_OK = False

# Ścieżki do modeli można nadpisać ENV lub ustawić w config/voice.toml → loader je wczyta.
PIPER_MODEL = os.getenv("PIPER_MODEL", "/home/pi/models/piper/pl_PL-gosia-medium.onnx")
VOSK_MODEL = os.getenv("VOSK_MODEL", "/home/pi/models/vosk/vosk-model-small-pl-0.22")

# Cache instancji lokalnych backendów
_local_piper_voice = None
_local_vosk_model = None


def _get_local_piper_voice():
    """Zwraca piper.PiperVoice (singleton) lub podnosi RuntimeError, gdy brak modułu/modelu."""
    if not _PIPER_OK:
        raise RuntimeError("piper module not available (pip install piper-tts)")
    global _local_piper_voice
    if _local_piper_voice is None:
        if not os.path.isfile(PIPER_MODEL):
            raise RuntimeError(f"Piper model not found: {PIPER_MODEL}")
        _local_piper_voice = piper.PiperVoice(PIPER_MODEL)
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
    n = len(pcm) // frame_len
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
    # zabezpieczenie zakresu
    g = max(0.1, min(gain, 3.0))
    return audioop.mul(pcm, 2, g)


# ── resampling ────────────────────────────────────────────────────────────────


def _resample_to(pcm: bytes, in_sr: int, in_ch: int, target_sr: int, target_ch: int) -> bytes:
    out, _ = audioop.ratecv(pcm, 2, in_ch, in_sr, target_sr, None)
    if target_ch == 2 and in_ch == 1:
        out = audioop.tostereo(out, 2, 1, 1)
    elif target_ch == 1 and in_ch == 2:
        out = audioop.tomono(out, 2, 0.5, 0.5)

    # shaping (fade + tail + opcjonalny gain)
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

    # 1) jeśli to WAV → ewentualny resampling i shaping, potem zwrot WAV
    got = _read_wav_params(audio)
    if got:
        pcm, in_sr, in_ch, in_sw = got
        if in_sw == 2 and (in_sr != target_sr or in_ch != target_ch):
            pcm = _resample_to(pcm, in_sr, in_ch, target_sr, target_ch)
            in_sr, in_ch = target_sr, target_ch
        else:
            # nawet jeśli parametry pasują, zastosuj fade/tail/gain
            if in_sw == 2:
                pcm = _apply_fade(pcm, in_sr, in_ch, 2, fade_in_ms, fade_out_ms)
                pcm = _append_tail(pcm, in_sr, in_ch, tail_ms)
                pcm = _maybe_gain(pcm, gain)
        return _wrap_wav(pcm, in_sr, in_ch, 2 if in_sw == 2 else in_sw)

    # 2) MP3/OGG → dekoduj do WAV narzędziem
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

    # 3) awaryjnie: RAW PCM16 mono
    try:
        sr = int(sample_rate or 24000)
        pcm = _resample_to(audio, sr, 1, target_sr, target_ch)
        return _wrap_wav(pcm, target_sr, target_ch, 2)
    except Exception:
        return None


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
            pcm += struct.pack("<hh", s, s)  # stereo L/R
    # fade + tail + gain tak samo jak dla TTS
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

        # backend/provide: dopuszczamy aliasy "provider", "tts"
        backend = (payload.get("backend") or payload.get("provider") or payload.get("tts") or "").strip().lower()

        # 1) Kanał lokalny (Piper) – na życzenie albo z configu (patrz niżej)
        if backend in ("local", "piper"):
            if not _PIPER_OK:
                return jsonify({"status": "error", "error": "piper module not available"}), 500
            try:
                voice = _get_local_piper_voice()
                # Piper generuje PCM 16-bit, zwykle 22_050 Hz, mono
                pcm = voice.synthesize(text)
                sr = 22050
                ch = 1
                # Reshape do ustawień globalnych (fade/tail/gain + resample)
                target_sr = int(os.environ.get("VOICE_RATE", "48000"))
                target_ch = int(os.environ.get("VOICE_CHANNELS", "2"))
                pcm2 = _resample_to(pcm, sr, ch, target_sr, target_ch)
                wav = _wrap_wav(pcm2, target_sr, target_ch, 2)
            except Exception as e:
                return jsonify({"status": "error", "error": f"local piper failed: {e}"}), 500

            if request.args.get("b64") == "1":
                b64 = base64.b64encode(wav).decode("ascii")
                return jsonify({"status": "ok", "fmt": "wav", "audio_b64": b64})
            return Response(wav, mimetype="audio/wav", headers={"Content-Disposition": "inline; filename=tts.wav"})

        # 2) Pozostałe kanały – pozostawiamy dotychczasową ścieżkę (OpenAI/Gemini)
        from . import config as voice_config
        from .tts import TTSConfig, synthesize

        # Nadpisanie części configu przez payload (opcjonalne)
        overrides = {}
        tts_pairs = []
        for k in ("backend", "provider", "format", "voice", "model"):
            if k in payload:
                # "provider" i "backend" traktujemy zamiennie → sprowadzamy do backend
                key = "backend" if k in ("backend", "provider") else k
                tts_pairs.append(f"{key}={payload[k]}")
        if tts_pairs:
            overrides = {"tts": voice_config.override_from_pairs("tts", tts_pairs)["tts"]}

        cfg = voice_config.load(None, overrides=overrides)

        # Jeśli w configu mamy backend=local/piper → obsłuż loklanie (kompatybilność)
        cfg_backend = str(cfg.get("tts", {}).get("backend", "")).lower()
        if cfg_backend in ("local", "piper"):
            if not _PIPER_OK:
                return jsonify({"status": "error", "error": "piper module not available"}), 500
            try:
                voice = _get_local_piper_voice()
                pcm = voice.synthesize(text)
                sr = 22050
                ch = 1
                target_sr = int(os.environ.get("VOICE_RATE", "48000"))
                target_ch = int(os.environ.get("VOICE_CHANNELS", "2"))
                pcm2 = _resample_to(pcm, sr, ch, target_sr, target_ch)
                wav = _wrap_wav(pcm2, target_sr, target_ch, 2)
            except Exception as e:
                return jsonify({"status": "error", "error": f"local piper failed: {e}"}), 500

            if request.args.get("b64") == "1":
                b64 = base64.b64encode(wav).decode("ascii")
                return jsonify({"status": "ok", "fmt": "wav", "audio_b64": b64})
            return Response(wav, mimetype="audio/wav", headers={"Content-Disposition": "inline; filename=tts.wav"})

        # W przeciwnym razie – dotychczasowy synth (OpenAI/Gemini)
        audio, sr, fmt = synthesize(text, TTSConfig(**cfg["tts"]))

        # Upewnij się, że to WAV (z fade/tail/gain/resample jeśli trzeba)
        wav = _ensure_wav_bytes(audio, sr, fmt)
        if not wav or not _is_wav(wav):
            return jsonify({"status": "error", "error": "synthesis produced no WAV"}), 500

        # tryb base64?
        if request.args.get("b64") == "1":
            b64 = base64.b64encode(wav).decode("ascii")
            return jsonify({"status": "ok", "fmt": "wav", "audio_b64": b64})

        # surowy WAV
        return Response(
            wav,
            mimetype="audio/wav",
            headers={"Content-Disposition": "inline; filename=tts.wav"},
        )

    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ───────────────────────────────────────────────────────────────────────────────
# NOWY endpoint: lokalny ASR (Vosk) – przyjmuje WAV (lub MP3/OGG), zwraca JSON
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

        # multipart/form-data z plikiem 'file'
        if "multipart" in ctype and request.files:
            f = request.files.get("file")
            if f:
                audio_bytes = f.read()
        if audio_bytes is None:
            # surowe body
            audio_bytes = request.get_data(cache=False, as_text=False) or None

        if not audio_bytes:
            return jsonify({"ok": False, "error": "no audio data"}), 400

        # Upewnij się, że mamy WAV
        wav = None
        if _is_wav(audio_bytes):
            wav = audio_bytes
        else:
            # MP3/OGG → dekoduj
            if _is_mp3(audio_bytes) or _is_ogg(audio_bytes) or "mpeg" in ctype or "ogg" in ctype:
                wav = _decode_with_tool_to_wav(audio_bytes)
            # opcjonalnie: potraktuj jako RAW PCM16 mono @ 16k (gdy klient wysyła czysty PCM)
            if wav is None and "application/octet-stream" in ctype:
                try:
                    pcm = audio_bytes
                    # RAW 16k → zrób WAV mono
                    wav = _wrap_wav(pcm, 16000, 1, 2)
                except Exception:
                    wav = None

        if not wav or not _is_wav(wav):
            return jsonify({"ok": False, "error": "unsupported or invalid audio"}), 400

        # Parametry WAV – Vosk wymaga 16k mono 16-bit
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
        import json as _json  # lokalny import, żeby nie kolidować z JSON w Flasku

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
