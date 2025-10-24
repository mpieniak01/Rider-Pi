# apps/voice/asr.py
"""Automatic speech recognition backends."""

from __future__ import annotations

import io
import json
import os
import wave
from dataclasses import dataclass
from typing import Any

from . import voice_logging as voice_logging


class ASRError(RuntimeError):
    pass


@dataclass
class ASRConfig:
    # Domyślne wartości pozwalają uruchomić backend bez nadmiaru konfiguracji
    backend: str = "openai"  # "openai" | "google" | "vosk" | "local"
    model: str | None = None  # nazwa/model backendu (np. dla OpenAI / Gemini)
    language: str | None = None  # preferowany język, np. "pl", "en", "auto"
    lang: str | None = None  # alias akceptowany przez CLI/konfig (mapowany na language)
    temperature: float = 0.0
    prompt: str | None = None
    vosk_model_dir: str | None = None
    whisper_model: str | None = None
    input_encoding: str | None = None
    timeout: float | None = None  # opcjonalny timeout (sekundy)

    # LOCAL HTTP (prosty REST: POST audio/wav -> JSON {text, language})
    base_url: str | None = None  # np. "http://127.0.0.1:8092"
    endpoint: str | None = None  # np. "/api/asr"
    content_type: str | None = None  # domyślnie "audio/wav"


@dataclass
class Transcript:
    text: str
    language: str
    raw: Any | None = None


# ──────────────────────────────────────────────────────────────────────────────
# Pomocnicze narzędzia audio


def _is_wav(b: bytes) -> bool:
    """Szybka detekcja nagłówka WAV (RIFF/WAVE)."""
    return len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WAVE"


def _pcm_to_wav_bytes(audio: bytes, sample_rate: int) -> bytes:
    """Opakuj surowe PCM S16_LE (mono) w kontener WAV."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16 bit
        wf.setframerate(int(sample_rate))
        wf.writeframes(audio)
    return buf.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# Normalizacja parametrów


def _norm_language(cfg: ASRConfig) -> str | None:
    """
    Spójne uzgadnianie nazwy języka:
    - używa cfg.language lub aliasu cfg.lang,
    - 'auto' traktujemy jako None (backend zdecyduje sam).
    """
    val = (cfg.language or cfg.lang or "").strip()
    if not val or val.lower() == "auto":
        return None
    return val


# ──────────────────────────────────────────────────────────────────────────────
# Publiczne API


def transcribe(
    audio: bytes,
    sample_rate: int,
    config: ASRConfig,
    logger: voice_logging.VoiceLogger | None = None,
) -> Transcript:
    backend = (config.backend or "stub").lower()
    logger = logger or voice_logging.get_logger("voice.asr")

    if not audio:
        raise ASRError("Empty audio buffer")

    if backend == "openai":
        return _openai_transcribe(
            audio,
            sample_rate,
            config,
            logger,
            language=_norm_language(config),
        )

    if backend == "google":
        return _gemini_transcribe(
            audio,
            sample_rate,
            config,
            logger,
            language=_norm_language(config),
        )

    if backend == "vosk":
        return _vosk_transcribe(
            audio,
            sample_rate,
            config,
            logger,
            language=_norm_language(config),
        )

    if backend == "local":
        return _local_http_transcribe(
            audio,
            sample_rate,
            config,
            logger,
            language=_norm_language(config),
        )

    raise ASRError(f"Unsupported ASR backend: {backend}")


# ──────────────────────────────────────────────────────────────────────────────
# Implementacje backendów


def _openai_transcribe(
    audio: bytes,
    sample_rate: int,
    config: ASRConfig,
    logger: voice_logging.VoiceLogger,
    *,
    language: str | None,
) -> Transcript:
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ASRError(f"OpenAI SDK unavailable: {exc}") from exc

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ASRError("OPENAI_API_KEY not configured")

    client = OpenAI(api_key=api_key)
    # per-request timeout (jeśli ustawiono)
    if config.timeout and config.timeout > 0:
        try:
            client = client.with_options(timeout=config.timeout)
        except Exception:
            # zgodność z różnymi wersjami SDK; jeśli brak with_options, pomiń
            pass

    # ZAWSZE wysyłaj kontener (WAV/MP3). Tu preferujemy WAV.
    if _is_wav(audio):
        wav_bytes = audio
    else:
        wav_bytes = _pcm_to_wav_bytes(audio, sample_rate)

    buffer = io.BytesIO(wav_bytes)
    buffer.name = "input.wav"  # OpenAI SDK lubi nazwę pliku przy file=...

    kwargs: dict[str, Any] = {
        "model": (config.model or "gpt-4o-mini-transcribe"),
        "file": buffer,
        "prompt": config.prompt,
        "temperature": config.temperature,
    }
    if language:  # nie wysyłaj language=None
        kwargs["language"] = language

    try:
        response = client.audio.transcriptions.create(**kwargs)
    except Exception as exc:
        raise ASRError(f"OpenAI transcription failed: {exc}") from exc

    text = getattr(response, "text", None) or ""
    lang_out = getattr(response, "language", None) or (language or "") or ""
    return Transcript(
        text=text.strip(),
        language=lang_out,
        raw=response.to_dict() if hasattr(response, "to_dict") else response,
    )


def _gemini_transcribe(
    audio: bytes,
    sample_rate: int,
    config: ASRConfig,
    logger: voice_logging.VoiceLogger,
    *,
    language: str | None,
) -> Transcript:
    """
    Google Gemini Speech-to-Text using multimodal model.
    Używa google-generativeai SDK i modeli multimodalnych jak gemini-1.5-flash.
    """
    try:
        import google.generativeai as genai  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ASRError(f"Google Generative AI SDK unavailable: {exc}") from exc

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ASRError("GOOGLE_API_KEY not configured")

    # Konfiguruj API
    genai.configure(api_key=api_key)

    # ZAWSZE wysyłaj kontener (WAV). Gemini akceptuje WAV/MP3.
    if _is_wav(audio):
        wav_bytes = audio
    else:
        wav_bytes = _pcm_to_wav_bytes(audio, sample_rate)

    # Użyj modelu multimodalnego (np. gemini-1.5-flash)
    model_name = config.model or "gemini-1.5-flash"

    try:
        logger.event("asr.gemini.request", model=model_name)

        # Gemini multimodal API przyjmuje audio jako część contentu
        model = genai.GenerativeModel(model_name=model_name)

        # Przygotuj prompt dla transkrypcji
        prompt = "Transcribe the following audio to text"
        if language:
            prompt += f" in {language} language"
        prompt += ". Return only the transcribed text without any additional formatting or commentary."

        # Wyślij audio jako część multimodalnego zapytania
        response = model.generate_content([prompt, {"mime_type": "audio/wav", "data": wav_bytes}])

        text = (response.text or "").strip()
        logger.event("asr.gemini.ok", chars=len(text))

        return Transcript(
            text=text,
            language=language or "",
            raw=response,
        )
    except Exception as exc:
        logger.event("asr.gemini.error", error=str(exc))
        raise ASRError(f"Gemini transcription failed: {exc}") from exc


def _vosk_transcribe(
    audio: bytes,
    sample_rate: int,
    config: ASRConfig,
    logger: voice_logging.VoiceLogger,
    *,
    language: str | None,
) -> Transcript:
    try:
        import vosk  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ASRError(f"Vosk backend unavailable: {exc}") from exc

    model_dir = config.vosk_model_dir or os.getenv("VOSK_MODEL_DIR")
    if not model_dir or not os.path.isdir(model_dir):
        raise ASRError("Vosk model directory missing; set vosk_model_dir")

    logger.event("asr.vosk.load", model_dir=model_dir)
    model = vosk.Model(model_dir)
    rec = vosk.KaldiRecognizer(model, sample_rate)
    rec.AcceptWaveform(audio)
    result = json.loads(rec.Result())

    text = (result.get("text") or "").strip()
    # Vosk zwykle nie zwraca jawnego 'language'; zachowaj preferencję wejściową
    lang_out = language or result.get("language", "") or ""
    return Transcript(text=text, language=lang_out)


def _local_http_transcribe(
    audio: bytes,
    sample_rate: int,
    config: ASRConfig,
    logger: voice_logging.VoiceLogger,
    *,
    language: str | None,
) -> Transcript:
    """
    Prosty backend HTTP:
      POST {base_url}{endpoint}
      Headers: Content-Type: audio/wav, Accept: application/json
      Body:   WAV (mono, 16 kHz preferowane)
      Response JSON: {"text": "...", "language": "pl"} (language opcjonalny)
    """
    try:
        import requests  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise ASRError(f"requests not available: {exc}") from exc

    # ZAWSZE wyślij WAV
    if _is_wav(audio):
        wav_bytes = audio
    else:
        wav_bytes = _pcm_to_wav_bytes(audio, sample_rate)

    base_url = (config.base_url or "").rstrip("/")
    endpoint = config.endpoint or "/api/asr"
    url = f"{base_url}{endpoint}"

    headers = {
        "Content-Type": (config.content_type or "audio/wav"),
        "Accept": "application/json",
    }
    timeout = config.timeout or 8.0

    logger.event("asr.local.request", url=url, bytes=len(wav_bytes))
    try:
        resp = requests.post(url, data=wav_bytes, headers=headers, timeout=timeout)
    except Exception as exc:
        logger.event("asr.local.error", error=str(exc))
        raise ASRError(f"LOCAL ASR: request failed: {exc}") from exc

    if resp.status_code >= 400:
        snippet = (resp.text or "")[:200]
        logger.event("asr.local.http_error", status=resp.status_code, body=snippet)
        raise ASRError(f"LOCAL ASR HTTP {resp.status_code}: {snippet}")

    try:
        data = resp.json()
    except Exception as e:
        raise ASRError("LOCAL ASR: invalid JSON") from e

    text_out = (data.get("text") or "").strip()
    lang_out = data.get("language") or language or ""

    if not text_out:
        raise ASRError("LOCAL ASR: empty transcript")

    logger.event("asr.local.ok", chars=len(text_out))
    return Transcript(text=text_out, language=str(lang_out), raw=data)
