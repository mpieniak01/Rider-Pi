"""Audio/model implementations forwarded through the live web namespace.

Only the explicitly selected worker profile loads a backend/model.
Public web helpers remain wrappers, preserving existing mocks and callers.
"""

from __future__ import annotations

import math


def _load_piper_backend(C) -> bool:
    if not C._PIPER_OK:
        try:
            from apps.voice.piper_compat import PiperVoice as voice_class

            C.PiperVoice = voice_class
            C._PIPER_OK = True
        except (ImportError, OSError):
            return False
    return True


def _load_vosk_backend(C) -> bool:
    if not C._VOSK_OK:
        try:
            from vosk import KaldiRecognizer as recognizer_class, Model as model_class

            C.KaldiRecognizer, C.Model = recognizer_class, model_class
            C._VOSK_OK = True
        except (ImportError, OSError):
            return False
    return True


def _resolve_piper_model_path(C, payload_voice: str | None = None) -> str:
    """Zwraca pełną ścieżkę do modelu Piper."""
    # 1) jawnie przez PIPER_MODEL
    if C.PIPER_MODEL:
        return C.PIPER_MODEL
    # 2) voice z payloadu (nazwa pliku) + DIR
    if payload_voice:
        return f"{C.PIPER_MODEL_DIR}/{payload_voice}"
    # 3) ENV voice + DIR
    if C.PIPER_VOICE:
        return f"{C.PIPER_MODEL_DIR}/{C.PIPER_VOICE}"
    # 4) fallback
    return f"{C.PIPER_MODEL_DIR}/pl_PL-mls-medium.onnx"


def _get_local_piper_voice(C, model_path: str | None = None):
    """
    Zwraca PiperVoice (singleton) lub podnosi RuntimeError, gdy brak modułu/modelu.
    Używa PiperVoice.load(model_path).
    """
    if not C._load_piper_backend():
        raise RuntimeError("piper module not available (apps.voice.piper_compat.PiperVoice)")

    if C._local_piper_voice is None:
        model = model_path or C._resolve_piper_model_path()
        if not C.os.path.isfile(model):
            raise RuntimeError(f"Piper model not found: {model}")
        C._local_piper_voice = C.PiperVoice.load(model)
    return C._local_piper_voice


def _get_local_vosk_model(C):
    """Zwraca vosk.Model (singleton) lub podnosi RuntimeError, gdy brak modułu/modelu."""
    if not C._load_vosk_backend():
        raise RuntimeError("vosk module not available (pip install vosk)")

    if C._local_vosk_model is None:
        if not C.os.path.isdir(C.VOSK_MODEL):
            raise RuntimeError(f"Vosk model not found dir: {C.VOSK_MODEL}")
        C._local_vosk_model = C.Model(C.VOSK_MODEL)
    return C._local_vosk_model


def _is_wav(C, b: bytes) -> bool:
    return len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WAVE"


def _read_wav_params(C, b: bytes):
    """Jeśli b to WAV → (pcm, sr, ch, sw). Inaczej None."""
    try:
        if not C._is_wav(b):
            return None
        bio = C.io.BytesIO(b)
        with C.wave.open(bio, "rb") as wf:
            ch = wf.getnchannels()
            sw = wf.getsampwidth()
            sr = wf.getframerate()
            pcm = wf.readframes(wf.getnframes())
        return pcm, sr, ch, sw
    except Exception:
        return None


def _wrap_wav(C, pcm: bytes, sr: int, ch: int, sw: int = 2) -> bytes:
    buf = C.io.BytesIO()
    with C.wave.open(buf, "wb") as wf:
        wf.setnchannels(ch)
        wf.setsampwidth(sw)
        wf.setframerate(int(sr))
        wf.writeframes(pcm)
    return buf.getvalue()


def _is_mp3(C, b: bytes) -> bool:
    return len(b) >= 3 and (b[:3] == b"ID3" or (b[0] == 0xFF and (b[1] & 0xE0) == 0xE0))


def _is_ogg(C, b: bytes) -> bool:
    return b.startswith(b"OggS")


def _decode_with_tool_to_wav(C, audio: bytes) -> bytes | None:
    """
    Dekoduj MP3/OGG do WAV narzędziem systemowym (mpg123 lub ffmpeg).
    Zwraca bajty WAV lub None.
    """
    if C.shutil.which("mpg123"):
        try:
            p = C.subprocess.run(
                ["mpg123", "-q", "-w", "-", "-"],
                input=audio,
                stdout=C.subprocess.PIPE,
                stderr=C.subprocess.DEVNULL,
                check=True,
            )
            if C._is_wav(p.stdout):
                return p.stdout
        except Exception:
            pass
    if C.shutil.which("ffmpeg"):
        try:
            p = C.subprocess.run(
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
                stdout=C.subprocess.PIPE,
                stderr=C.subprocess.DEVNULL,
                check=True,
            )
            if C._is_wav(p.stdout):
                return p.stdout
        except Exception:
            pass
    return None


def _apply_fade(
    C,
    pcm: bytes,
    sr: int,
    ch: int,
    sampwidth: int = 2,
    fade_in_ms: int = 15,
    fade_out_ms: int = 20,
) -> bytes:
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
            s = C.struct.unpack_from("<h", pcm, (i * ch + c) * 2)[0]
            C.struct.pack_into("<h", out, (i * ch + c) * 2, int(s * gain))

    # środek bez zmian
    start_mid = fi
    end_mid = n - fo
    if end_mid > start_mid:
        out[start_mid * frame_len : end_mid * frame_len] = pcm[start_mid * frame_len : end_mid * frame_len]

    # ramp-out
    for i in range(n - fo, n):
        gain = (n - i) / fo if fo else 1.0
        for c in range(ch):
            s = C.struct.unpack_from("<h", pcm, (i * ch + c) * 2)[0]
            C.struct.pack_into("<h", out, (i * ch + c) * 2, int(s * gain))

    return bytes(out)


def _append_tail(C, pcm: bytes, sr: int, ch: int, ms: int) -> bytes:
    frames = int(sr * ms / 1000) * ch
    if frames > 0:
        pcm += b"\x00\x00" * frames
    return pcm


def _maybe_gain(C, pcm: bytes, gain: float) -> bytes:
    if math.isclose(gain, 1.0, rel_tol=0.0, abs_tol=1e-9):
        return pcm
    g = max(0.1, min(gain, 3.0))
    return C.audioop.mul(pcm, 2, g)


def _resample_to(C, pcm: bytes, in_sr: int, in_ch: int, target_sr: int, target_ch: int) -> bytes:
    out, _ = C.audioop.ratecv(pcm, 2, in_ch, in_sr, target_sr, None)
    if target_ch == 2 and in_ch == 1:
        out = C.audioop.tostereo(out, 2, 1, 1)
    elif target_ch == 1 and in_ch == 2:
        out = C.audioop.tomono(out, 2, 0.5, 0.5)

    fade_in_ms = int(C.os.environ.get("VOICE_FADE_IN_MS", "15"))
    fade_out_ms = int(C.os.environ.get("VOICE_FADE_OUT_MS", "20"))
    tail_ms = int(C.os.environ.get("VOICE_TAIL_MS", "300"))
    gain = float(C.os.environ.get("VOICE_GAIN", "1.0"))

    out = C._apply_fade(out, target_sr, target_ch, 2, fade_in_ms, fade_out_ms)
    out = C._append_tail(out, target_sr, target_ch, tail_ms)
    out = C._maybe_gain(out, gain)
    return out


def _normalize_wav_params(context, params, target_sr, target_ch, fade_in_ms, fade_out_ms, tail_ms, gain):
    pcm, in_sr, in_ch, in_sw = params
    if in_sw == 2 and (in_sr != target_sr or in_ch != target_ch):
        pcm = context._resample_to(pcm, in_sr, in_ch, target_sr, target_ch)
        in_sr, in_ch = target_sr, target_ch
    elif in_sw == 2:
        pcm = context._apply_fade(pcm, in_sr, in_ch, 2, fade_in_ms, fade_out_ms)
        pcm = context._append_tail(pcm, in_sr, in_ch, tail_ms)
        pcm = context._maybe_gain(pcm, gain)
    return context._wrap_wav(pcm, in_sr, in_ch, in_sw)


def _ensure_wav_bytes(C, audio: bytes, sample_rate: int | None, fmt: str | None) -> bytes | None:
    """
    Upewnij się, że zwrócimy poprawny WAV @ VOICE_RATE/VOICE_CHANNELS.
    - przyjmujemy: WAV, MP3/OGG, lub (awaryjnie) RAW PCM16 mono @ sample_rate
    """
    target_sr = int(C.os.environ.get("VOICE_RATE", "48000"))
    target_ch = int(C.os.environ.get("VOICE_CHANNELS", "2"))

    fade_in_ms = int(C.os.environ.get("VOICE_FADE_IN_MS", "15"))
    fade_out_ms = int(C.os.environ.get("VOICE_FADE_OUT_MS", "20"))
    tail_ms = int(C.os.environ.get("VOICE_TAIL_MS", "300"))
    gain = float(C.os.environ.get("VOICE_GAIN", "1.0"))

    got = C._read_wav_params(audio)
    if got:
        return _normalize_wav_params(C, got, target_sr, target_ch, fade_in_ms, fade_out_ms, tail_ms, gain)

    if C._is_mp3(audio) or C._is_ogg(audio) or (fmt or "").lower() in ("mp3", "mpeg", "audio/mpeg", "ogg"):
        wav = C._decode_with_tool_to_wav(audio)
        if wav and C._is_wav(wav):
            got = C._read_wav_params(wav)
            if got:
                return _normalize_wav_params(C, got, target_sr, target_ch, fade_in_ms, fade_out_ms, tail_ms, gain)
        return None

    # 3) RAW PCM16 mono
    try:
        sr = int(sample_rate or 24000)
        pcm = C._resample_to(audio, sr, 1, target_sr, target_ch)
        return C._wrap_wav(pcm, target_sr, target_ch, 2)
    except Exception:
        return None


def _remove_piper_temp(context, path):
    try:
        context.os.remove(path)
    except Exception:
        pass


def _piper_file_method(context, fn, text):
    with context.tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        try:
            fn(text, tmp_path)
        except TypeError:
            try:
                fn(wav_file=tmp_path, text=text)
            except TypeError:
                fn(text=text, wav_file=tmp_path)
        with open(tmp_path, "rb") as handle:
            wav_bytes = handle.read()
        _remove_piper_temp(context, tmp_path)
        if context._is_wav(wav_bytes):
            got = context._read_wav_params(wav_bytes)
            return wav_bytes, (got[1] if got else None)
    except Exception:
        _remove_piper_temp(context, tmp_path)
    return None


def _piper_pcm_bytes(pcm):
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

    return pcm_bytes


def _piper_cli_audio(context, text, model_path):
    # 4) OSTATECZNY fallback: CLI `piper` (jeśli dostępny)
    if context.shutil.which("piper") and (
        model_path or context.os.getenv("PIPER_MODEL") or context.os.getenv("PIPER_VOICE")
    ):
        mp = model_path or context.os.getenv("PIPER_MODEL")
        if not mp:
            mp = (
                f'{context.os.getenv("PIPER_MODEL_DIR", "/home/pi/robot/models/piper").rstrip("/")}/'
                f'{context.os.getenv("PIPER_VOICE", "pl_PL-mls-medium.onnx")}'
            )
        try:
            # `piper -m <model> -f -` → WAV na stdout, tekst na stdin
            p = context.subprocess.run(
                ["piper", "-m", mp, "-f", "-"],
                input=(text + "\n").encode("utf-8"),
                capture_output=True,
                check=True,
            )
            if context._is_wav(p.stdout):
                got = context._read_wav_params(p.stdout)
                return p.stdout, (got[1] if got else None)
            raise RuntimeError(f"piper CLI returned non-WAV (stderr={p.stderr.decode('utf-8', 'ignore')[:200]})")
        except Exception as e:
            raise RuntimeError(f"piper CLI failed: {e}") from e

    raise RuntimeError("Piper synth failed: no supported method")


def _piper_pcm_audio(context, voice, text):
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
        pcm_bytes = _piper_pcm_bytes(pcm)

        target_sr = int(context.os.environ.get("VOICE_RATE", "48000"))
        target_ch = int(context.os.environ.get("VOICE_CHANNELS", "2"))
        ch = 1
        wav_bytes = context._wrap_wav(
            context._resample_to(pcm_bytes, int(sr or 22050), ch, target_sr, target_ch),
            target_sr,
            target_ch,
            2,
        )
        return wav_bytes, target_sr

    return None


def _piper_synthesize_wav_bytes(C, voice, text: str, model_path: str | None = None) -> tuple[bytes, int | None]:
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

    for method in ("synthesize_wav", "synthesize_to_wav", "save_wav", "synthesize_to_file", "synthesize"):
        if hasattr(voice, method):
            result = _piper_file_method(C, getattr(voice, method), text)
            if result is not None:
                return result

    result = _piper_pcm_audio(C, voice, text)
    if result is not None:
        return result

    return _piper_cli_audio(C, text, model_path)


def _asr_request_audio(context):
    audio_bytes: bytes | None = None
    ctype = (context.request.headers.get("Content-Type") or "").lower()

    if "multipart" in ctype and context.request.files:
        f = context.request.files.get("file")
        if f:
            audio_bytes = f.read()
    if audio_bytes is None:
        audio_bytes = context.request.get_data(cache=False, as_text=False) or None

    return audio_bytes, ctype


def _asr_input_wav(context, audio_bytes, ctype):
    wav = None
    if context._is_wav(audio_bytes):
        wav = audio_bytes
    else:
        if context._is_mp3(audio_bytes) or context._is_ogg(audio_bytes) or "mpeg" in ctype or "ogg" in ctype:
            wav = context._decode_with_tool_to_wav(audio_bytes)
        if wav is None and "application/octet-stream" in ctype:
            try:
                pcm = audio_bytes
                wav = context._wrap_wav(pcm, 16000, 1, 2)
            except Exception:
                wav = None

    return wav


def api_asr(C):
    """
    POST audio (preferowane Content-Type: audio/wav) lub multipart 'file'.
    Zwraca JSON: { ok: true, text: "..." }
    """
    try:
        if not C._load_vosk_backend():
            return C.jsonify({"ok": False, "error": "vosk module not available"}), 500

        audio_bytes, ctype = _asr_request_audio(C)

        if not audio_bytes:
            return C.jsonify({"ok": False, "error": "no audio data"}), 400

        wav = _asr_input_wav(C, audio_bytes, ctype)

        if not wav or not C._is_wav(wav):
            return C.jsonify({"ok": False, "error": "unsupported or invalid audio"}), 400

        got = C._read_wav_params(wav)
        if not got:
            return C.jsonify({"ok": False, "error": "invalid wav"}), 400
        pcm, in_sr, in_ch, in_sw = got
        if in_sw != 2:
            return C.jsonify({"ok": False, "error": "expected 16-bit PCM"}), 400

        target_sr = 16000
        target_ch = 1
        if in_sr != target_sr or in_ch != target_ch:
            pcm = C._resample_to(pcm, in_sr, in_ch, target_sr, target_ch)

        model = C._get_local_vosk_model()
        rec = C.KaldiRecognizer(model, target_sr)
        rec.AcceptWaveform(pcm)
        import json as _json

        try:
            data = _json.loads(rec.FinalResult() or "{}")
        except Exception:
            data = {"text": ""}

        return C.jsonify({"ok": True, "text": (data.get("text") or "").strip()}), 200

    except Exception as e:
        return C.jsonify({"ok": False, "error": str(e)}), 500
