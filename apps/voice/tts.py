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


class TTSError(RuntimeError):
    pass


@dataclass
class TTSConfig:
    backend: str = "openai"  # "openai" | "google"
    voice: str | None = None  # np. "alloy" / "Kore"
    model: str | None = None  # np. "gpt-4o-mini-tts" / "gemini-2.5-flash-preview-tts"
    format: str = "wav"  # "wav" | "mp3" (i tak sprowadzimy do WAV w synth)
    timeout: float | None = None  # [s] – timeout per-request (stream/synth)
    piper_model: str | None = None  # rezerwa; bez użycia tutaj
    piper_config: dict | None = None  # rezerwa
    # NOWE: STRICT — gdy "realtime", blokujemy wszelkie REST/HTTP TTS
    transport: str = "file"  # "file" | "realtime"


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
            logger.event("tts.decode.ffmpeg_failed", extra={"data": str(e)})
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
            logger.event("tts.decode.mpg123_failed", extra={"data": str(e)})
    return None


# ───── public API ─────────────────────────────────────────────────────────────


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
        logger.event("tts.strict.realtime_block", extra={"data": {"msg": "TTS REST disabled when transport=realtime"}})
        raise TTSError("TTS REST disabled when transport=realtime")

    backend = (config.backend or "openai").lower()

    # Streaming obsługujemy tylko dla OpenAI; dla Google pomijamy ścieżkę stream
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
        audio_bytes, sample_rate, audio_fmt = synthesize(text, config, logger)
    except TTSError as exc:
        logger.event("tts.speak.failed", error=str(exc))
        return TTSStreamResult(False, None, "", 0, streamed=False)

    try:
        play_bytes(audio_bytes, audio_fmt, playback, logger)
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


def synthesize(text: str, config: TTSConfig, logger: voice_logging.VoiceLogger | None = None) -> tuple[bytes, int, str]:
    """
    Pełna synteza (REST), zwraca (audio_bytes, sample_rate, audio_format).
    STRICT: zabronione, gdy transport=realtime.
    """
    logger = logger or voice_logging.get_logger("voice.tts")
    if (config.transport or "").lower() == "realtime":
        logger.event("tts.strict.realtime_block", extra={"data": {"msg": "TTS REST disabled when transport=realtime"}})
        raise TTSError("TTS REST disabled when transport=realtime")

    backend = (config.backend or "openai").lower()

    if backend == "openai":
        return _tts_openai(text, config, logger)
    elif backend == "google":
        return _tts_gemini(text, config, logger)
    else:
        raise TTSError(f"Unsupported TTS backend: {backend}")


def _tts_openai(text: str, config: TTSConfig, logger: voice_logging.VoiceLogger) -> tuple[bytes, int, str]:
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

            extra_gain = float(os.environ.get("VOICE_GAIN", "1.0"))
            if sw == 2:
                pcm = _normalize_16bit(pcm, target_peak=30000, extra_gain=extra_gain)
                pcm = _fade_in_out(pcm, sr, ch, ms_in=5, ms_out=60)
            wav_bytes = _wrap_wav(pcm, sr, ch, 2 if sw == 2 else sw)

            return wav_bytes, sr, "wav"

        except requests.RequestException as e:
            logger.event("tts.openai.net_retry", extra={"data": {"attempt": attempt, "error": str(e)}})
            last_err = e
            time.sleep(0.6 * (attempt + 1))

    # jeśli tu dotarliśmy — nie udało się
    raise TTSError(f"OpenAI TTS request failed: {last_err or 'unknown error'}")


def _tts_gemini(text: str, config: TTSConfig, logger: voice_logging.VoiceLogger) -> tuple[bytes, int, str]:
    """
    Google Gemini Text-to-Speech using native audio generation.
    Zwraca ZAWSZE WAV (audio_bytes, sample_rate, "wav").
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise TTSError("GOOGLE_API_KEY not configured")

    try:
        from google import genai
        from google.genai import types
    except Exception as exc:  # pragma: no cover - optional dependency
        raise TTSError(f"Google GenAI SDK unavailable: {exc}") from exc

    model_name = config.model or "gemini-2.5-flash-preview-tts"
    voice_name = config.voice or "Kore"  # Default voice

    logger.event("tts.gemini.request", model=model_name, voice=voice_name)

    try:
        # Inicjalizuj klienta
        client = genai.Client(api_key=api_key)

        # Konfiguracja TTS z native audio
        response = client.models.generate_content(
            model=model_name,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice_name,
                        )
                    )
                ),
            ),
        )

        # Wyciągnij dane audio z odpowiedzi (bezpiecznie)
        cand = (getattr(response, "candidates", None) or [None])[0]
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        inline = None
        for p in parts:
            idata = getattr(p, "inline_data", None)
            if idata is not None and getattr(idata, "data", None):
                inline = idata
                break
        if inline is None:
            pf = getattr(response, "prompt_feedback", None)
            raise TTSError(f"No audio data in Gemini response (parts empty). prompt_feedback={pf!r}")

        raw = inline.data
        # Google SDK bywa niespójne: czasem bytes, czasem base64 string
        if isinstance(raw, str):
            try:
                raw = base64.b64decode(raw)
            except Exception as e:
                raise TTSError(f"Gemini inline_data.data not decodable base64: {e}") from e

        # Rozpoznaj typ: WAV czy czysty PCM
        if _is_wav(raw):
            wav_bytes = raw
            pcm, sr, ch, sw = _read_wav(wav_bytes)
        else:
            # Załóżmy 16-bit PCM mono 24 kHz (obecne zachowanie Gemini TTS)
            sr = 24000
            ch = 1
            sw = 2
            pcm = raw
            wav_bytes = _wrap_wav(pcm, sr, ch, sw)

        # Opcjonalna normalizacja i fade (jak w OpenAI)
        extra_gain = float(os.environ.get("VOICE_GAIN", "1.0"))
        if sw == 2:
            pcm = _normalize_16bit(pcm, target_peak=30000, extra_gain=extra_gain)
            pcm = _fade_in_out(pcm, sr, ch, ms_in=5, ms_out=60)
        wav_bytes = _wrap_wav(pcm, sr, ch, 2 if sw == 2 else sw)

        logger.event("tts.gemini.ok", bytes=len(wav_bytes), sample_rate=sr)
        return wav_bytes, sr, "wav"

    except Exception as exc:
        logger.event("tts.gemini.error", error=str(exc))
        if isinstance(exc, TTSError):
            raise
        raise TTSError(f"Gemini TTS failed: {exc}") from exc


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
    )

    try:
        async for chunk in text_generator:
            if not chunk:
                continue

            buffer += chunk

            # Sprawdź, czy bufor zawiera koniec zdania
            # Szukamy ostatniego znaku końca zdania
            last_ending_idx = -1
            for i in range(len(buffer) - 1, -1, -1):
                if buffer[i] in sentence_endings:
                    last_ending_idx = i
                    break

            # Jeśli znaleziono koniec zdania i jest wystarczająco dużo tekstu
            if last_ending_idx >= 0 and last_ending_idx >= 10:  # minimum 10 znaków
                # Wydziel zdanie do syntezy
                sentence = buffer[: last_ending_idx + 1].strip()
                buffer = buffer[last_ending_idx + 1 :]

                if sentence:
                    # Synteza i odtwarzanie zdania
                    logger.event("tts.stream_async.sentence", chars=len(sentence))
                    try:
                        # Uruchom blokującą operację w executorze
                        import asyncio

                        loop = asyncio.get_event_loop()

                        # Capture sentence in closure to avoid loop variable binding issue
                        def _make_tts_func(text: str):
                            def _sync_tts():
                                return speak(text, config_override, playback, logger, accumulate=False)

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
