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


def speak(
    text: str,
    config: TTSConfig,
    playback: PlaybackConfig,
    logger: voice_logging.VoiceLogger | None = None,
    *,
    accumulate: bool = False,
) -> TTSStreamResult:
    """Wygeneruj mowę i odtwórz ją; w STRICT mode NIE używa REST, gdy transport=realtime."""

    logger = logger or voice_logging.get_logger("voice.tts")
    text = text.strip()
    if not text:
        return TTSStreamResult(ok=False, streamed=False)

    # STRICT: zabroń REST (zarówno streaming HTTP, jak i synth) w trybie realtime
    if (config.transport or "").lower() == "realtime":
        logger.event(
            "tts.strict.realtime_block",
            extra={"data": {"msg": "TTS REST disabled when transport=realtime"}},
        )
        raise TTSError("TTS REST disabled when transport=realtime")

    backend = (config.backend or "openai").lower()

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
        start_ts = time.time()
        first_chunk_at: float | None = None
        ok_stream = True
        mp3_bytes: bytes | None = None
        try:
            for chunk in _openai_stream_chunks(text, config, stream_fmt, api_key=api_key):
                stream.write(chunk)
                if first_chunk_at is None:
                    first_chunk_at = time.time()
                    logger.event(
                        "tts.stream.ttfb",
                        backend=stream.backend,
                        latency=first_chunk_at - start_ts,
                    )
        except TTSError as exc:
            logger.event("tts.stream.backend_error", backend=stream.backend, error=str(exc))
            ok_stream = False
        except PlaybackError as exc:
            logger.event("tts.stream.player_write_failed", backend=stream.backend, error=str(exc))
            ok_stream = False
        except Exception as exc:  # pragma: no cover - system-level failure
            logger.event("tts.stream.error", backend=stream.backend, error=str(exc))
            ok_stream = False
        finally:
            try:
                player_ok, mp3_bytes, stderr = stream.close()
            except Exception as exc:  # pragma: no cover - system-level failure
                logger.event("tts.stream.close_error", backend=stream.backend, error=str(exc))
                player_ok, mp3_bytes, stderr = False, None, None
            ok_stream = ok_stream and player_ok
            if not player_ok and stderr:
                logger.event("tts.stream.player_stderr", backend=stream.backend, stderr=stderr)

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

        logger.event("tts.stream.failed", backend=stream.backend)
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
    logger = logger or voice_logging.get_logger("voice.tts")
    if (config.transport or "").lower() == "realtime":
        logger.event(
            "tts.strict.realtime_block",
            extra={"data": {"msg": "TTS REST disabled when transport=realtime"}},
        )
        raise TTSError("TTS REST disabled when transport=realtime")

    backend = (config.backend or "openai").lower()

    if backend == "openai":
        return _tts_openai(text, config, logger)
    if backend.strip() in {"google", "gemini"}:
        raise TTSError("Google/Gemini SDK integration is disabled; select a supported TTS backend")
    if backend == "local":
        return _tts_local(text, config, logger)

    raise TTSError(f"Unsupported TTS backend: {backend}")


def _tts_openai(text: str, config: TTSConfig, logger: voice_logging.VoiceLogger) -> tuple[bytes, int, int, str]:
    """
    OpenAI Text-to-Speech (v1/audio/speech).
    Zwraca ZAWSZE WAV (audio_bytes, sample_rate, channels, "wav"), niezależnie od proszonego formatu.
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
            resp = requests.post(url, json=payload, headers=headers, timeout=(config.timeout or 40))
            ctype = (resp.headers.get("Content-Type") or "").lower()
            body = resp.content

            if resp.status_code >= 400:
                logger.event(
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

            # === START FIX: Resampling + Tail ===
            # Wymuszamy 48kHz / 2 kanały (Stereo) - tak jak robi to działający `local`
            TARGET_SR = 48000
            TARGET_CH = 2

            if sw == 2:  # Resampling działa tylko na 16-bit
                try:
                    pcm, sr, ch = _resample_to(pcm, sr, ch, TARGET_SR, TARGET_CH)
                    sw = 2  # _resample_to zachowuje 16-bit
                except Exception as e:
                    logger.event("tts.openai.resample_failed", error=str(e))
                    # Kontynuuj z oryginalnym audio, jeśli resampling zawiedzie
            # === END FIX ===

            extra_gain = float(os.environ.get("VOICE_GAIN", "1.0"))
            if sw == 2:
                pcm = _normalize_16bit(pcm, target_peak=30000, extra_gain=extra_gain)
                pcm = _fade_in_out(pcm, sr, ch, ms_in=5, ms_out=60)
                pcm = _append_tail(pcm, sr, ch, 300)
                pcm = _maybe_gain(pcm, extra_gain)
            wav_bytes = _wrap_wav(pcm, sr, ch, 2 if sw == 2 else sw)

            return wav_bytes, sr, ch, "wav"

        except requests.RequestException as e:
            logger.event(
                "tts.openai.net_retry",
                extra={"data": {"attempt": attempt, "error": str(e)}},
            )
            last_err = e
            time.sleep(0.6 * (attempt + 1))

    # jeśli tu dotarliśmy — nie udało się
    raise TTSError(f"OpenAI TTS request failed: {last_err or 'unknown error'}")


def _tts_local(text: str, config: TTSConfig, logger: voice_logging.VoiceLogger) -> tuple[bytes, int, int, str]:
    """
    Lokalny backend HTTP:
      POST {base_url}{endpoint}
      Headers: Accept: audio/wav (domyślnie) lub wg config.accept
      JSON body: {"text": "...", "voice": "pl_m"} (model/format opcjonalnie)
      Response: audio/wav (preferowane) lub audio/mpeg albo JSON z base64
    """
    base_url = (config.base_url or "").rstrip("/")
    endpoint = config.endpoint or "/api/tts"
    url = f"{base_url}{endpoint}"
    timeout = config.timeout or 15.0
    accept = config.accept or "audio/wav, audio/*;q=0.9, application/json;q=0.5"

    payload = {"text": text, "voice": (config.voice or "pl_m")}
    if config.model:
        payload["model"] = config.model
    if config.format:
        payload["format"] = config.format

    headers = {"Accept": accept, "Content-Type": "application/json"}

    logger.event("tts.local.request", url=url, accept=accept, voice=payload["voice"])
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except Exception as exc:
        logger.event("tts.local.error", error=str(exc))
        raise TTSError(f"LOCAL TTS: request failed: {exc}") from exc

    ctype = (resp.headers.get("Content-Type") or "").lower()
    body = resp.content or b""

    if resp.status_code >= 400:
        snippet = (resp.text or "")[:200]
        logger.event("tts.local.http_error", status=resp.status_code, body=snippet)
        raise TTSError(f"LOCAL TTS HTTP {resp.status_code}: {snippet}")

    # 1) audio/wav — najlepszy przypadek
    if ctype.startswith("audio/wav") or _is_wav(body):
        wav_bytes = body
        try:
            pcm, sr, ch, sw = _read_wav(wav_bytes)
        except Exception as e:
            raise TTSError("LOCAL TTS: returned WAV unreadable") from e

    # 2) audio/mpeg — konwersja do WAV
    elif (
        "audio/mpeg" in ctype or body[:3] == b"ID3" or (len(body) > 2 and body[0] == 0xFF and (body[1] & 0xE0) == 0xE0)
    ):
        w = _decode_mp3_to_wav(body, logger)
        if not w:
            raise TTSError("LOCAL TTS: MP3 decode failed (no ffmpeg/mpg123?)")
        wav_bytes = w
        pcm, sr, ch, sw = _read_wav(wav_bytes)

    # 3) application/json — spróbuj base64
    elif "application/json" in ctype:
        try:
            j = resp.json()
        except Exception as e:
            raise TTSError("LOCAL TTS: JSON parse failed") from e
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
            raise TTSError("LOCAL TTS: no audio in JSON response")
        raw = base64.b64decode(b64)
        if _is_wav(raw):
            wav_bytes = raw
            pcm, sr, ch, sw = _read_wav(raw)
        else:
            w = _decode_mp3_to_wav(raw, logger)
            if not w:
                # dopuszczamy czysty PCM 16-bit mono 16 kHz
                pcm = raw
                sr, ch, sw = 16000, 1, 2
                wav_bytes = _wrap_wav(pcm, sr, ch, sw)
            else:
                wav_bytes = w
                pcm, sr, ch, sw = _read_wav(wav_bytes)

    else:
        # nieznany content-type — spróbuj jako WAV, potem MP3, na końcu załóż PCM
        if _is_wav(body):
            wav_bytes = body
            pcm, sr, ch, sw = _read_wav(wav_bytes)
        else:
            w = _decode_mp3_to_wav(body, logger)
            if w:
                wav_bytes = w
                pcm, sr, ch, sw = _read_wav(wav_bytes)
            else:
                # ostatnia próba: czysty PCM
                pcm, sr, ch, sw = body, 16000, 1, 2
                wav_bytes = _wrap_wav(pcm, sr, ch, sw)

    # Konwersja do 16-bit jeśli potrzeba
    extra_gain = float(os.environ.get("VOICE_GAIN", "1.0"))
    if sw != 2:
        try:
            pcm = audioop.lin2lin(pcm, sw, 2)
            sw = 2
        except Exception:
            pass

    # === START FIX: Resampling + Tail + Gain (jak w OpenAI) ===
    # Wymuszamy 48kHz / 2 kanały (Stereo) - tak jak w pozostałych backendach
    TARGET_SR = 48000
    TARGET_CH = 2

    if sw == 2:  # Resampling działa tylko na 16-bit
        try:
            pcm, sr, ch = _resample_to(pcm, sr, ch, TARGET_SR, TARGET_CH)
            sw = 2  # _resample_to zachowuje 16-bit
        except Exception as e:
            logger.event("tts.local.resample_failed", error=str(e))
            # Kontynuuj z oryginalnym audio, jeśli resampling zawiedzie
    # === END FIX ===

    # Normalizacja i fade (jak w innych backendach)
    if sw == 2:
        pcm = _normalize_16bit(pcm, target_peak=30000, extra_gain=extra_gain)
        pcm = _fade_in_out(pcm, sr, ch, ms_in=5, ms_out=60)
        pcm = _append_tail(pcm, sr, ch, 300)  # <--- POPRAWKA: Dodanie ciszy
    wav_bytes = _wrap_wav(pcm, sr, ch, 2 if sw == 2 else sw)

    logger.event("tts.local.ok", bytes=len(wav_bytes), sample_rate=sr, channels=ch)
    return wav_bytes, sr, ch, "wav"


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
    logger = logger or voice_logging.get_logger("voice.tts")

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
    config_override = TTSConfig(
        backend=config.backend,
        voice=config.voice,
        model=config.model,
        format=config.format,
        timeout=config.timeout,
        piper_model=config.piper_model,
        piper_config=config.piper_config,
        transport="file",  # Override to bypass blocking
        base_url=config.base_url,
        endpoint=config.endpoint,
        accept=config.accept,
    )

    try:
        async for chunk in text_generator:
            if not chunk:
                continue

            buffer += chunk

            # Szukamy ostatniego znaku końca zdania
            last_ending_idx = -1
            for i in range(len(buffer) - 1, -1, -1):
                if buffer[i] in sentence_endings:
                    last_ending_idx = i
                    break

            if last_ending_idx >= 0 and last_ending_idx >= 10:  # minimum 10 znaków
                sentence = buffer[: last_ending_idx + 1].strip()
                buffer = buffer[last_ending_idx + 1 :]

                if sentence:
                    logger.event("tts.stream_async.sentence", chars=len(sentence))
                    try:
                        import asyncio

                        loop = asyncio.get_event_loop()

                        def _make_tts_func(text: str):
                            def _sync_tts():
                                return speak(
                                    text,
                                    config_override,
                                    playback,
                                    logger,
                                    accumulate=False,
                                )

                            return _sync_tts

                        await loop.run_in_executor(None, _make_tts_func(sentence))

                    except Exception as exc:
                        logger.event("tts.stream_async.sentence_error", error=str(exc))
                        # Kontynuuj mimo błędu

        # Jeśli został tekst w buforze, wypowiedz go
        if buffer.strip():
            logger.event("tts.stream_async.final_buffer", chars=len(buffer))
            try:
                import asyncio

                loop = asyncio.get_event_loop()
                final_text = buffer.strip()

                def _make_tts_func(text: str):
                    def _sync_tts():
                        return speak(text, config_override, playback, logger, accumulate=False)

                    return _sync_tts

                await loop.run_in_executor(None, _make_tts_func(final_text))
            except Exception as exc:
                logger.event("tts.stream_async.final_error", error=str(exc))

        logger.event("tts.stream_async.complete")
        return TTSStreamResult(ok=True, streamed=True)

    except Exception as exc:
        logger.event("tts.stream_async.error", error=str(exc))
        return TTSStreamResult(ok=False, streamed=False)


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
        "pl_m": "pl_PL-gosia-medium.onnx",
        "pl_f": "pl_PL-gosia-medium.onnx",
        "pl": "pl_PL-gosia-medium.onnx",
    }
    base = MAP.get(voice_id, "pl_PL-gosia-medium.onnx")
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
