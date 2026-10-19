# apps/voice/tts.py
from __future__ import annotations

import audioop
import base64
import io
import os
import time
import wave
from dataclasses import dataclass, replace

import requests

from . import voice_logging as voice_logging
from .audio.playback import PlaybackConfig, PlaybackError, play_bytes, start_stream
from .common import ensure_openai_key
from .tts_audio import (
    _append_tail as _append_tail,
    _decode_mp3_to_wav as _decode_mp3_to_wav,
    _fade_in_out as _fade_in_out,
    _is_wav as _is_wav,
    _maybe_gain as _maybe_gain,
    _normalize_16bit as _normalize_16bit,
    _read_wav as _read_wav,
    _resample_to as _resample_to,
    _wrap_wav as _wrap_wav,
)

_LOGGER_NAME = "voice.tts"
_REST_DISABLED = "TTS REST disabled when transport=realtime"
_JSON_CONTENT_TYPE = "application/json"
_PIPER_MODEL = "pl_PL-gosia-medium.onnx"
_AUDIO_ACCEPT = "audio/wav, audio/*;q=0.9, application/json;q=0.5"


class TTSError(RuntimeError):
    pass


@dataclass
class TTSConfig:
    backend: str = "openai"  # "openai" | "local"
    voice: str | None = None  # np. "alloy" / "pl_m"
    model: str | None = None  # np. "gpt-4o-mini-tts"
    format: str = "wav"  # "wav" | "mp3" (i tak sprowadzimy do WAV w synth)
    timeout: float | None = None  # [s] – timeout per-request (stream/synth)
    piper_model: str | None = None  # rezerwa; bez użycia tutaj
    piper_config: dict | None = None  # rezerwa
    # STRICT — gdy "realtime", blokujemy wszelkie REST/HTTP TTS
    transport: str = "file"  # "file" | "realtime"
    # LOCAL HTTP
    base_url: str | None = None  # np. "http://127.0.0.1:8092"
    endpoint: str | None = None  # np. "/api/tts"
    accept: str | None = None  # np. "audio/wav" | "audio/mpeg" | "application/octet-stream"


@dataclass
class TTSStreamResult:
    ok: bool
    audio: bytes | None = None
    audio_format: str = ""
    sample_rate: int = 0
    streamed: bool = False
    backend: str | None = None


def _assert_rest_enabled(config, logger):
    if (config.transport or "").lower() == "realtime":
        logger.event(
            "tts.strict.realtime_block",
            extra={"data": {"msg": _REST_DISABLED}},
        )
        raise TTSError(_REST_DISABLED)


def _tts_backend(config):
    return (config.backend or "openai").lower()


def speak(
    text: str,
    config: TTSConfig,
    playback: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None,
    *,
    accumulate: bool = False,
) -> TTSStreamResult:
    """Wygeneruj mowę i odtwórz ją; w STRICT mode NIE używa REST, gdy transport=realtime."""

    logger = logger or voice_logging.get_logger(_LOGGER_NAME)
    text = text.strip()
    if not text:
        return TTSStreamResult(ok=False, streamed=False)

    # STRICT: zabroń REST (zarówno streaming HTTP, jak i synth) w trybie realtime
    _assert_rest_enabled(config, logger)

    backend = _tts_backend(config)

    # Streaming obsługujemy tylko dla OpenAI; dla local pomijamy ścieżkę stream
    stream_fmt = "mp3"
    should_start_stream = accumulate and backend == "openai"

    if should_start_stream:
        api_key = ensure_openai_key(logger)
        if not api_key:
            return TTSStreamResult(ok=False, streamed=False)

        stream = start_stream(stream_fmt, playback, logger, accumulate=True)
    else:
        stream = None

    if stream:
        result = _play_openai_stream(text, config, stream_fmt, api_key, stream, logger, accumulate)
        if result is not None:
            return result
    else:
        logger.debug("tts.stream.unavailable")

    # fallback: pełny synth + odtwarzanie
    try:
        audio_bytes, sample_rate, channels, audio_fmt = synthesize(text, config, logger)
    except TTSError as exc:
        logger.event("tts.speak.failed", error=str(exc))
        return TTSStreamResult(False, None, "", 0, streamed=False)

    try:
        play_bytes(audio_bytes, audio_fmt, playback, logger, sample_rate=sample_rate, channels=channels)
    except PlaybackError as exc:
        logger.event("tts.playback.failed", error=str(exc))
        return TTSStreamResult(False, None, audio_fmt, sample_rate, streamed=False)

    audio_data = audio_bytes if accumulate else None
    return TTSStreamResult(True, audio_data, audio_fmt, sample_rate, streamed=False)


def _write_openai_stream(text, config, fmt, api_key, stream, logger, start_ts):
    first_chunk_at = None
    try:
        for chunk in _openai_stream_chunks(text, config, fmt, api_key=api_key):
            stream.write(chunk)
            if first_chunk_at is None:
                first_chunk_at = time.time()
                logger.event("tts.stream.ttfb", backend=stream.backend, latency=first_chunk_at - start_ts)
    except TTSError as exc:
        logger.event("tts.stream.backend_error", backend=stream.backend, error=str(exc))
        return False, first_chunk_at
    except PlaybackError as exc:
        logger.event("tts.stream.player_write_failed", backend=stream.backend, error=str(exc))
        return False, first_chunk_at
    except Exception as exc:  # pragma: no cover - system-level failure
        logger.event("tts.stream.error", backend=stream.backend, error=str(exc))
        return False, first_chunk_at
    return True, first_chunk_at


def _close_openai_stream(stream, logger):
    try:
        player_ok, mp3_bytes, stderr = stream.close()
    except Exception as exc:  # pragma: no cover - system-level failure
        logger.event("tts.stream.close_error", backend=stream.backend, error=str(exc))
        return False, None
    if not player_ok and stderr:
        logger.event("tts.stream.player_stderr", backend=stream.backend, stderr=stderr)
    return player_ok, mp3_bytes


def _accumulated_stream_audio(mp3_bytes, fmt, logger, accumulate):
    if not accumulate or not mp3_bytes:
        return None, fmt, 0
    wav_bytes = _decode_mp3_to_wav(mp3_bytes, logger)
    if not wav_bytes:
        return mp3_bytes, fmt, 0
    try:
        _, sample_rate, _, _ = _read_wav(wav_bytes)
    except Exception:
        sample_rate = 0
    return wav_bytes, "wav", sample_rate


def _play_openai_stream(text, config, fmt, api_key, stream, logger, accumulate):
    start_ts = time.time()
    try:
        ok, first_chunk_at = _write_openai_stream(text, config, fmt, api_key, stream, logger, start_ts)
    finally:
        player_ok, mp3_bytes = _close_openai_stream(stream, logger)
    if not (ok and player_ok):
        logger.event("tts.stream.failed", backend=stream.backend)
        return None
    payload = {"backend": stream.backend, "duration": time.time() - start_ts}
    if first_chunk_at is not None:
        payload["ttfb"] = first_chunk_at - start_ts
    logger.event("tts.stream.success", **payload)
    audio, audio_format, sample_rate = _accumulated_stream_audio(mp3_bytes, fmt, logger, accumulate)
    return TTSStreamResult(True, audio, audio_format, sample_rate, streamed=True, backend=stream.backend)


def _openai_stream_chunks(text: str, config: TTSConfig, fmt: str, *, api_key: str):
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    timeout_s = config.timeout or 45
    try:
        context = client.audio.speech.with_streaming_response.create(
            model=(config.model or "gpt-4o-mini-tts"),
            voice=(config.voice or "alloy"),
            input=text,
            timeout=timeout_s,
        )
    except Exception as exc:
        raise TTSError(f"OpenAI TTS streaming init failed: {exc}") from exc
    with context as response:
        for chunk in response.iter_bytes(8192):
            if chunk:
                yield chunk


def synthesize(
    text: str,
    config: TTSConfig,
    logger: voice_logging.VoiceLogger | None = None,
) -> tuple[bytes, int, int, str]:
    """
    Pełna synteza (REST), zwraca (audio_bytes, sample_rate, channels, audio_format).
    STRICT: zabronione, gdy transport=realtime.
    """
    logger = logger or voice_logging.get_logger(_LOGGER_NAME)
    _assert_rest_enabled(config, logger)

    backend = _tts_backend(config)

    if backend == "openai":
        return _tts_openai(text, config, logger)
    if backend.strip() in {"google", "gemini"}:
        raise TTSError("Google/Gemini SDK integration is disabled; select a supported TTS backend")
    if backend == "local":
        return _tts_local(text, config, logger)

    raise TTSError(f"Unsupported TTS backend: {backend}")


def _nested_base64(value):
    for key in ("b64", "base64", "data"):
        if isinstance(value.get(key), str):
            return value[key]
    return None


def _response_base64(payload):
    for key in ("audio", "audio_b64", "bytes", "data", "b64"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            encoded = _nested_base64(value)
            if encoded:
                return encoded
    return None


def _json_response_audio(response, prefix=""):
    try:
        payload = response.json()
    except Exception as exc:
        raise TTSError(f"{prefix}JSON parse failed") from exc
    encoded = _response_base64(payload)
    if not encoded:
        message = "no audio in JSON response" if prefix else "No audio in JSON response"
        raise TTSError(f"{prefix}{message}")
    return base64.b64decode(encoded)


def _looks_like_mp3(body, content_type):
    return (
        "audio/mpeg" in content_type
        or body[:3] == b"ID3"
        or (len(body) > 2 and body[0] == 0xFF and (body[1] & 0xE0) == 0xE0)
    )


def _decode_openai_response(response, logger):
    content_type = (response.headers.get("Content-Type") or "").lower()
    body = response.content
    if content_type.startswith("audio/wav") or _is_wav(body):
        return body
    if _looks_like_mp3(body, content_type):
        message = "MP3 decode failed (no ffmpeg/mpg123?)"
    elif _JSON_CONTENT_TYPE in content_type:
        body = _json_response_audio(response)
        if _is_wav(body):
            return body
        message = "Base64 audio not WAV/MP3 or decode failed"
    else:
        message = f"Unknown audio type (ctype={content_type or 'n/a'})"
    wav_bytes = _decode_mp3_to_wav(body, logger)
    if not wav_bytes:
        raise TTSError(message)
    return wav_bytes


def _prepare_tts_pcm(pcm, sr, ch, sw, logger, backend):
    if sw != 2:
        try:
            pcm = audioop.lin2lin(pcm, sw, 2)
            sw = 2
        except Exception:
            pass
    if sw == 2:
        try:
            pcm, sr, ch = _resample_to(pcm, sr, ch, 48000, 2)
        except Exception as exc:
            logger.event(f"tts.{backend}.resample_failed", error=str(exc))
    return pcm, sr, ch, sw


def _finish_tts_wav(pcm, sr, ch, sw, extra_gain, *, apply_gain=False):
    if sw == 2:
        pcm = _normalize_16bit(pcm, target_peak=30000, extra_gain=extra_gain)
        pcm = _fade_in_out(pcm, sr, ch, ms_in=5, ms_out=60)
        pcm = _append_tail(pcm, sr, ch, 300)
        if apply_gain:
            pcm = _maybe_gain(pcm, extra_gain)
    return _wrap_wav(pcm, sr, ch, sw), sr, ch, "wav"


def _openai_response_wav(response, logger):
    wav_bytes = _decode_openai_response(response, logger)
    try:
        pcm, sr, ch, sw = _read_wav(wav_bytes)
    except Exception as exc:
        raise TTSError("Returned WAV unreadable") from exc
    pcm, sr, ch, sw = _prepare_tts_pcm(pcm, sr, ch, sw, logger, "openai")
    extra_gain = float(os.environ.get("VOICE_GAIN", "1.0"))
    return _finish_tts_wav(pcm, sr, ch, sw, extra_gain, apply_gain=True)


def _tts_openai(text: str, config: TTSConfig, logger: voice_logging.VoiceLogger) -> tuple[bytes, int, int, str]:
    """Request OpenAI speech and normalize successful responses to WAV, retrying three times."""
    api_key = ensure_openai_key(logger)
    if not api_key:
        raise TTSError("OPENAI_API_KEY not configured")
    payload = {
        "model": config.model or "gpt-4o-mini-tts",
        "voice": config.voice or "alloy",
        "input": text,
        "format": (config.format or "wav").lower(),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": _JSON_CONTENT_TYPE,
        "Accept": _AUDIO_ACCEPT,
    }
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.post(
                "https://api.openai.com/v1/audio/speech", json=payload, headers=headers, timeout=config.timeout or 40
            )
            if resp.status_code >= 400:
                logger.event(
                    "tts.openai.http_error",
                    extra={"data": {"attempt": attempt, "status": resp.status_code, "text": resp.text[:400]}},
                )
                raise TTSError(f"OpenAI TTS error: {resp.status_code} {resp.text[:200]}")
            return _openai_response_wav(resp, logger)
        except TTSError as exc:
            last_err = exc
        except requests.RequestException as exc:
            logger.event("tts.openai.net_retry", extra={"data": {"attempt": attempt, "error": str(exc)}})
            last_err = exc
        time.sleep(0.6 * (attempt + 1))
    raise TTSError(f"OpenAI TTS request failed: {last_err or 'unknown error'}")


def _local_response_pcm(response, logger):
    content_type = (response.headers.get("Content-Type") or "").lower()
    body = response.content or b""
    if content_type.startswith("audio/wav") or _is_wav(body):
        try:
            return _read_wav(body)
        except Exception as exc:
            raise TTSError("LOCAL TTS: returned WAV unreadable") from exc
    if _looks_like_mp3(body, content_type):
        wav_bytes = _decode_mp3_to_wav(body, logger)
        if not wav_bytes:
            raise TTSError("LOCAL TTS: MP3 decode failed (no ffmpeg/mpg123?)")
        return _read_wav(wav_bytes)
    if _JSON_CONTENT_TYPE in content_type:
        body = _json_response_audio(response, "LOCAL TTS: ")
        if _is_wav(body):
            return _read_wav(body)
    wav_bytes = _decode_mp3_to_wav(body, logger)
    if wav_bytes:
        return _read_wav(wav_bytes)
    # Local servers may return raw 16-bit mono PCM at 16 kHz.
    return body, 16000, 1, 2


def _tts_local(text: str, config: TTSConfig, logger: voice_logging.VoiceLogger) -> tuple[bytes, int, int, str]:
    """Synthesize over local HTTP, retaining WAV, MP3, JSON/base64 and raw PCM support."""
    url = f"{(config.base_url or '').rstrip('/')}{config.endpoint or '/api/tts'}"
    accept = config.accept or _AUDIO_ACCEPT
    payload = {"text": text, "voice": config.voice or "pl_m"}
    if config.model:
        payload["model"] = config.model
    if config.format:
        payload["format"] = config.format
    logger.event("tts.local.request", url=url, accept=accept, voice=payload["voice"])
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Accept": accept, "Content-Type": _JSON_CONTENT_TYPE},
            timeout=config.timeout or 15.0,
        )
    except Exception as exc:
        logger.event("tts.local.error", error=str(exc))
        raise TTSError(f"LOCAL TTS: request failed: {exc}") from exc
    if resp.status_code >= 400:
        snippet = (resp.text or "")[:200]
        logger.event("tts.local.http_error", status=resp.status_code, body=snippet)
        raise TTSError(f"LOCAL TTS HTTP {resp.status_code}: {snippet}")
    pcm, sr, ch, sw = _local_response_pcm(resp, logger)
    extra_gain = float(os.environ.get("VOICE_GAIN", "1.0"))
    pcm, sr, ch, sw = _prepare_tts_pcm(pcm, sr, ch, sw, logger, "local")
    result = _finish_tts_wav(pcm, sr, ch, sw, extra_gain)
    logger.event("tts.local.ok", bytes=len(result[0]), sample_rate=sr, channels=ch)
    return result


async def speak_stream(
    text_generator,
    config: TTSConfig,
    playback: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None,
) -> TTSStreamResult:
    """
    Asynchroniczna wersja TTS dla strumienia tekstu.
    Akceptuje async generator produkujący fragmenty tekstu.
    Buforuje tekst do momentu wykrycia końca zdania (., !, ?),
    a następnie wysyła całe zdanie do syntezy i odtwarzania.
    Używane w trybie transport=realtime.
    """
    logger = logger or voice_logging.get_logger(_LOGGER_NAME)

    # Streaming jest obecnie wspierany tylko dla OpenAI — więc tu używamy ensure_openai_key
    api_key = ensure_openai_key(logger)
    if not api_key:
        return TTSStreamResult(ok=False, streamed=False)

    # Bufor na akumulację tekstu do końca zdania
    buffer = ""
    sentence_endings = {".", "!", "?", "\n"}
    model = config.model or "gpt-4o-mini-tts"
    voice = config.voice or "alloy"

    logger.event("tts.stream_async.start", model=model, voice=voice)

    # Tworzymy kopię konfiguracji z wyłączonym blokowaniem realtime
    # ponieważ speak_stream jest dedykowane dla trybu realtime
    config_override = replace(config, transport="file")

    try:
        async for chunk in text_generator:
            if not chunk:
                continue

            buffer += chunk

            sentence, buffer = _take_stream_sentence(buffer, sentence_endings)
            if sentence:
                logger.event("tts.stream_async.sentence", chars=len(sentence))
                await _speak_async_sentence(sentence, config_override, playback, logger, "sentence_error")

        if buffer.strip():
            logger.event("tts.stream_async.final_buffer", chars=len(buffer))
            await _speak_async_sentence(buffer.strip(), config_override, playback, logger, "final_error")

        logger.event("tts.stream_async.complete")
        return TTSStreamResult(ok=True, streamed=True)

    except Exception as exc:
        logger.event("tts.stream_async.error", error=str(exc))
        return TTSStreamResult(ok=False, streamed=False)


def _take_stream_sentence(buffer, sentence_endings):
    for index in range(len(buffer) - 1, -1, -1):
        if buffer[index] in sentence_endings:
            if index >= 10:
                return buffer[: index + 1].strip(), buffer[index + 1 :]
            break
    return "", buffer


async def _speak_async_sentence(text, config, playback, logger, error_event):
    import asyncio
    from functools import partial

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, partial(speak, text, config, playback, logger, accumulate=False))
    except Exception as exc:
        logger.event(f"tts.stream_async.{error_event}", error=str(exc))


def _piper_synthesize_wav(
    voice,
    text: str,
    length_scale=1.0,
    noise_scale=0.667,
    noise_w=0.8,
    sentence_silence=0.6,
) -> bytes:
    """Zwraca bajty pliku WAV (mono, 16-bit) z PiperVoice."""

    sr = getattr(getattr(voice, "config", None), "sample_rate", None) or 22050
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(sr)
        # piper-tts >=1.2.0: synthesize(text, wav_file, **params)
        voice.synthesize(
            text,
            w,
            length_scale=length_scale,
            noise_scale=noise_scale,
            noise_w=noise_w,
            sentence_silence=sentence_silence,
        )
    return buf.getvalue(), sr


# ===== PIPER helpers =====
def _piper_model_paths(voice_id: str, model_dir: str):
    import os

    MAP = {
        "pl_m": _PIPER_MODEL,
        "pl_f": _PIPER_MODEL,
        "pl": _PIPER_MODEL,
    }
    base = MAP.get(voice_id, _PIPER_MODEL)
    model = os.path.join(model_dir, base)
    cfg = model + ".json"
    return model, cfg


def _load_piper_voice(voice_id: str, model_dir: str):
    import json
    import os

    from piper.voice import PiperVoice

    model, cfg = _piper_model_paths(voice_id, model_dir)
    if not os.path.isfile(model):
        raise RuntimeError(f"Piper model not found: {model}")
    if not os.path.isfile(cfg):
        raise RuntimeError(f"Piper config not found: {cfg}")
    try:
        with open(cfg, encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("sample_rate") in (None, 0):
            meta["sample_rate"] = 22050
            with open(cfg, "w", encoding="utf-8") as f:
                json.dump(meta, f)
    except Exception:
        pass
    voice = PiperVoice.load(model, cfg)
    if getattr(getattr(voice, "config", None), "sample_rate", None) in (None, 0):
        voice.config.sample_rate = 22050
    return voice


def _piper_synthesize_wav(
    voice,
    text: str,
    length_scale=1.0,
    noise_scale=0.667,
    noise_w=0.8,
    sentence_silence=0.6,
):
    sr = getattr(getattr(voice, "config", None), "sample_rate", None) or 22050
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        # piper-tts>=1.2.0 API: synthesize(text, wav_file, **kwargs)
        voice.synthesize(
            text,
            w,
            length_scale=length_scale,
            noise_scale=noise_scale,
            noise_w=noise_w,
            sentence_silence=sentence_silence,
        )
    return buf.getvalue(), sr


# ===== end helpers =====
