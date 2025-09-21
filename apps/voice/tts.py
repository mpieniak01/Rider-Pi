# apps/voice/tts.py
from __future__ import annotations

import audioop
import base64
import io
import os
import time
import wave
from dataclasses import dataclass

import requests

from . import voice_logging as voice_logging
from .common import ensure_openai_key
from .playback import PlaybackConfig, PlaybackError, play_bytes, start_stream


class TTSError(RuntimeError):
    pass


@dataclass
class TTSConfig:
    backend: str = "openai"  # na razie "openai"
    voice: str | None = None  # np. "alloy"
    model: str | None = None  # np. "gpt-4o-mini-tts"
    format: str = "wav"  # "wav" | "mp3" (i tak sprowadzimy do WAV)
    piper_model: str | None = None  # rezerwa; bez użycia tutaj
    piper_config: dict | None = None  # rezerwa


@dataclass
class TTSStreamResult:
    ok: bool
    audio: bytes | None = None
    audio_format: str = ""
    sample_rate: int = 0
    streamed: bool = False
    backend: str | None = None


# ───── helpers ────────────────────────────────────────────────────────────────


def _is_wav(b: bytes) -> bool:
    return len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WAVE"


def _wrap_wav(pcm: bytes, sr: int, ch: int, sw: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(ch)
        wf.setsampwidth(sw)
        wf.setframerate(int(sr))
        wf.writeframes(pcm)
    return buf.getvalue()


def _read_wav(b: bytes) -> tuple[bytes, int, int, int]:
    with wave.open(io.BytesIO(b), "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        pcm = wf.readframes(wf.getnframes())
    return pcm, sr, ch, sw


def _fade_in_out(pcm: bytes, sr: int, ch: int, ms_in: int = 5, ms_out: int = 40) -> bytes:
    """Delikatny fade-in/out, by uniknąć „pyknięć”. Operuje na 16-bit mono/stereo."""
    if not pcm or ch not in (1, 2):
        return pcm
    n_samples = len(pcm) // 2
    if n_samples == 0:
        return pcm
    import array

    a = array.array("h")
    a.frombytes(pcm)
    # fade-in
    n_in = min(n_samples // ch, int(sr * ms_in / 1000))
    for i in range(n_in):
        scale = (i + 1) / max(1, n_in)
        if ch == 1:
            a[i] = int(a[i] * scale)
        else:
            a[2 * i] = int(a[2 * i] * scale)
            a[2 * i + 1] = int(a[2 * i + 1] * scale)
    # fade-out
    n_out = min(n_samples // ch, int(sr * ms_out / 1000))
    for j in range(n_out):
        scale = (n_out - j) / max(1, n_out)
        idx = n_samples // ch - 1 - j
        if ch == 1:
            a[idx] = int(a[idx] * scale)
        else:
            a[2 * idx] = int(a[2 * idx] * scale)
            a[2 * idx + 1] = int(a[2 * idx + 1] * scale)
    return a.tobytes()


def _normalize_16bit(pcm: bytes, target_peak: int = 30000, extra_gain: float = 1.0) -> bytes:
    """
    Prosta normalizacja: skaluje tak, by pik był ~target_peak,
    potem stosuje VOICE_GAIN (extra_gain). Zabezpiecza przed clippingiem.
    """
    if not pcm:
        return pcm
    import array

    a = array.array("h")
    a.frombytes(pcm)
    peak = max((abs(x) for x in a), default=1)
    gain = min(10.0, (target_peak / max(1, peak)) * float(extra_gain))
    if abs(gain - 1.0) < 1e-3:
        return pcm
    for i, v in enumerate(a):
        a[i] = int(max(-32768, min(32767, v * gain)))
    return a.tobytes()


def _decode_mp3_to_wav(audio_bytes: bytes, logger: voice_logging.VoiceLogger) -> bytes | None:
    """
    Spróbuj zdekodować MP3 → WAV narzędziami systemowymi (ffmpeg/mpg123).
    Zwraca WAV lub None (gdy brak narzędzi albo dekoder zawiedzie).
    """
    import shutil
    import subprocess

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
                input=audio_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            if _is_wav(p.stdout):
                return p.stdout
        except Exception as e:
            logger.warning("tts.decode.ffmpeg_failed", extra={"data": str(e)})
    if shutil.which("mpg123"):
        try:
            p = subprocess.run(
                ["mpg123", "-q", "-w", "-", "-"],
                input=audio_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            if _is_wav(p.stdout):
                return p.stdout
        except Exception as e:
            logger.warning("tts.decode.mpg123_failed", extra={"data": str(e)})
    return None


def speak(
    text: str,
    config: TTSConfig,
    playback: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None,
    *,
    accumulate: bool = False,
) -> TTSStreamResult:
    """Wygeneruj mowę i odtwórz ją, preferując strumieniowanie."""

    logger = logger or voice_logging.get_logger("voice.tts")
    text = text.strip()
    if not text:
        return TTSStreamResult(ok=False, streamed=False)

    if not ensure_openai_key(logger):
        return TTSStreamResult(ok=False, streamed=False)

    stream_fmt = "mp3"
    stream = start_stream(stream_fmt, playback, logger, accumulate=accumulate)
    if stream:
        start_ts = time.time()
        first_chunk_at: float | None = None
        ok_stream = True
        mp3_bytes: bytes | None = None
        try:
            for chunk in _openai_stream_chunks(text, config, stream_fmt):
                stream.write(chunk)
                if first_chunk_at is None:
                    first_chunk_at = time.time()
                    logger.debug(
                        "tts.stream.ttfb",
                        backend=stream.backend,
                        latency=first_chunk_at - start_ts,
                    )
        except TTSError as exc:
            logger.warning("tts.stream.backend_error", backend=stream.backend, error=str(exc))
            ok_stream = False
        except PlaybackError as exc:
            logger.warning("tts.stream.player_write_failed", backend=stream.backend, error=str(exc))
            ok_stream = False
        except Exception as exc:  # pragma: no cover - system-level failure
            logger.warning("tts.stream.error", backend=stream.backend, error=str(exc))
            ok_stream = False
        finally:
            try:
                player_ok, mp3_bytes, stderr = stream.close()
            except Exception as exc:  # pragma: no cover - system-level failure
                logger.warning("tts.stream.close_error", backend=stream.backend, error=str(exc))
                player_ok, mp3_bytes, stderr = False, None, None
            ok_stream = ok_stream and player_ok
            if not player_ok and stderr:
                logger.warning("tts.stream.player_stderr", backend=stream.backend, stderr=stderr)

        if ok_stream:
            total = time.time() - start_ts
            payload = {"backend": stream.backend, "duration": total}
            if first_chunk_at is not None:
                payload["ttfb"] = first_chunk_at - start_ts
            logger.event("tts.stream.success", **payload)

            audio_bytes: bytes | None = None
            audio_format = stream_fmt
            sample_rate = 0
            if accumulate and mp3_bytes:
                wav_bytes = _decode_mp3_to_wav(mp3_bytes, logger)
                if wav_bytes:
                    audio_bytes = wav_bytes
                    try:
                        _, sr, _, _ = _read_wav(wav_bytes)
                    except Exception:
                        sr = 0
                    audio_format = "wav"
                    sample_rate = sr
                else:
                    audio_bytes = mp3_bytes
            return TTSStreamResult(
                ok=True,
                audio=audio_bytes,
                audio_format=audio_format,
                sample_rate=sample_rate,
                streamed=True,
                backend=stream.backend,
            )

        logger.warning("tts.stream.failed", backend=stream.backend)
    else:
        logger.debug("tts.stream.unavailable")

    try:
        audio_bytes, sample_rate, audio_fmt = synthesize(text, config, logger)
    except TTSError as exc:
        logger.error("tts.speak.failed", error=str(exc))
        return TTSStreamResult(False, None, "", 0, streamed=False)

    try:
        play_bytes(audio_bytes, audio_fmt, playback, logger, blocking=True)
    except PlaybackError as exc:
        logger.error("tts.playback.failed", error=str(exc))
        return TTSStreamResult(False, None, audio_fmt, sample_rate, streamed=False)

    audio_data = audio_bytes if accumulate else None
    return TTSStreamResult(True, audio_data, audio_fmt, sample_rate, streamed=False)


def _openai_stream_chunks(text: str, config: TTSConfig, fmt: str):
    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise TTSError(f"OpenAI SDK unavailable: {exc}") from exc

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    # Część wersji SDK nie przyjmuje `format` → spróbuj z, a w razie TypeError bez.
    try:
        try:
            context = client.audio.speech.with_streaming_response.create(
                model=(config.model or "gpt-4o-mini-tts"),
                voice=(config.voice or "alloy"),
                input=text,
                # format=fmt,  # preferowane, gdy obsługiwane
                timeout=45,
            )
        except TypeError:
            context = client.audio.speech.with_streaming_response.create(
                model=(config.model or "gpt-4o-mini-tts"),
                voice=(config.voice or "alloy"),
                input=text,
                timeout=45,
            )
    except Exception as exc:
        raise TTSError(f"OpenAI TTS streaming init failed: {exc}") from exc

    with context as response:
        for chunk in response.iter_bytes(8192):
            if chunk:
                yield chunk


# ───── public API ─────────────────────────────────────────────────────────────


def synthesize(
    text: str, config: TTSConfig, logger: voice_logging.VoiceLogger | None = None
) -> tuple[bytes, int, str]:
    backend = (config.backend or "openai").lower()
    logger = logger or voice_logging.get_logger("voice.tts")

    if backend != "openai":
        raise TTSError(f"Unsupported TTS backend: {backend}")

    return _tts_openai(text, config, logger)


def _tts_openai(
    text: str, config: TTSConfig, logger: voice_logging.VoiceLogger
) -> tuple[bytes, int, str]:
    """
    OpenAI Text-to-Speech (v1/audio/speech).
    Zwraca ZAWSZE WAV (audio_bytes, sample_rate, "wav"), niezależnie od proszonego formatu.
    VOICE_GAIN (env) działa przez normalizację 16-bit + fade-in/out.
    """
    api_key = ensure_openai_key(logger)
    if not api_key:
        raise TTSError("OPENAI_API_KEY not configured")

    url = "https://api.openai.com/v1/audio/speech"
    model = config.model or "gpt-4o-mini-tts"
    voice = config.voice or "alloy"
    requested_fmt = (config.format or "wav").lower()

    payload = {"model": model, "voice": voice, "input": text, "format": requested_fmt}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # spróbujmy wymóc audio zamiast JSON-ów
        "Accept": "audio/wav, audio/*;q=0.9, application/json;q=0.5",
    }

    last_err = None
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=40)
            ctype = (resp.headers.get("Content-Type") or "").lower()
            body = resp.content

            if resp.status_code >= 400:
                logger.error(
                    "tts.openai.http_error",
                    extra={
                        "data": {
                            "attempt": attempt,
                            "status": resp.status_code,
                            "text": resp.text[:400],
                        }
                    },
                )
                last_err = TTSError(f"OpenAI TTS error: {resp.status_code} {resp.text[:200]}")
                time.sleep(0.6 * (attempt + 1))
                continue

            # 1) audio/wav — idealnie
            if ctype.startswith("audio/wav") or _is_wav(body):
                wav_bytes = body

            # 2) audio/mpeg — dekoduj do WAV
            elif (
                "audio/mpeg" in ctype
                or body[:3] == b"ID3"
                or (len(body) > 2 and body[0] == 0xFF and (body[1] & 0xE0) == 0xE0)
            ):
                w = _decode_mp3_to_wav(body, logger)
                if not w:
                    last_err = TTSError("MP3 decode failed (no ffmpeg/mpg123?)")
                    time.sleep(0.6 * (attempt + 1))
                    continue
                wav_bytes = w

            # 3) application/json — możliwe audio w base64
            elif "application/json" in ctype:
                try:
                    j = resp.json()
                except Exception:
                    last_err = TTSError("JSON parse failed")
                    time.sleep(0.6 * (attempt + 1))
                    continue
                b64 = None
                for k in ("audio", "audio_b64", "bytes", "data", "b64"):
                    v = j.get(k)
                    if isinstance(v, str):
                        b64 = v
                        break
                    if isinstance(v, dict):
                        for kk in ("b64", "base64", "data"):
                            if isinstance(v.get(kk), str):
                                b64 = v[kk]
                                break
                        if b64:
                            break
                if not b64:
                    last_err = TTSError("No audio in JSON response")
                    time.sleep(0.6 * (attempt + 1))
                    continue
                raw = base64.b64decode(b64)
                if _is_wav(raw):
                    wav_bytes = raw
                else:
                    w = _decode_mp3_to_wav(raw, logger)
                    if not w:
                        last_err = TTSError("Base64 audio not WAV/MP3 or decode failed")
                        time.sleep(0.6 * (attempt + 1))
                        continue
                    wav_bytes = w

            else:
                # nieznany content-type — spróbuj jako WAV, potem jako MP3
                if _is_wav(body):
                    wav_bytes = body
                else:
                    w = _decode_mp3_to_wav(body, logger)
                    if not w:
                        last_err = TTSError(f"Unknown audio type (ctype={ctype or 'n/a'})")
                        time.sleep(0.6 * (attempt + 1))
                        continue
                    wav_bytes = w

            # mamy WAV — normalizacja 16-bit + fade
            try:
                pcm, sr, ch, sw = _read_wav(wav_bytes)
            except Exception:
                last_err = TTSError("Returned WAV unreadable")
                time.sleep(0.6 * (attempt + 1))
                continue

            # 🔧 konwersja do 16-bit, jeżeli potrzeba
            if sw != 2:
                try:
                    pcm = audioop.lin2lin(pcm, sw, 2)
                    sw = 2
                except Exception:
                    pass

            extra_gain = float(os.environ.get("VOICE_GAIN", "1.0"))
            if sw == 2:
                pcm = _normalize_16bit(pcm, target_peak=30000, extra_gain=extra_gain)
                pcm = _fade_in_out(pcm, sr, ch, ms_in=5, ms_out=60)
            wav_bytes = _wrap_wav(pcm, sr, ch, 2 if sw == 2 else sw)

            return wav_bytes, sr, "wav"

        except requests.RequestException as e:
            logger.warning(
                "tts.openai.net_retry", extra={"data": {"attempt": attempt, "error": str(e)}}
            )
            last_err = e
            time.sleep(0.6 * (attempt + 1))

    # jeśli tu dotarliśmy — nie udało się
    raise TTSError(f"OpenAI TTS request failed: {last_err or 'unknown error'}")
