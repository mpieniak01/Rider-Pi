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
    backend: str = "openai"  # "openai" | "vosk" | (inne w przyszłości)
    model: str | None = None  # nazwa/model backendu (np. dla OpenAI)
    language: str | None = None  # preferowany język, np. "pl", "en", "auto"
    lang: str | None = None  # alias akceptowany przez CLI/konfig (mapowany na language)
    temperature: float = 0.0
    prompt: str | None = None
    vosk_model_dir: str | None = None
    whisper_model: str | None = None
    input_encoding: str | None = None
    timeout: float | None = None  # opcjonalny timeout (obecnie *nie* przekazujemy do SDK)


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
    """
    Opakuj surowe PCM S16_LE (mono) w kontener WAV.
    """
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

    if backend == "vosk":
        return _vosk_transcribe(
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

    # ZAWSZE wysyłaj kontener (WAV/MP3). Tu preferujemy WAV.
    if _is_wav(audio):
        wav_bytes = audio
    else:
        wav_bytes = _pcm_to_wav_bytes(audio, sample_rate)

    buffer = io.BytesIO(wav_bytes)
    buffer.name = "input.wav"  # OpenAI SDK lubi nazwę pliku przy file=...

    # Parametry wspierane przez endpoint transkrypcji:
    # language: może być None (auto), prompt/temperature wg modelu
    # (timeout trzymamy w configu, ale nie przekazujemy — SDK tego nie przyjmuje)
    try:
        response = client.audio.transcriptions.create(
            model=(config.model or "gpt-4o-mini-transcribe"),
            file=buffer,
            language=language,  # None => auto
            prompt=config.prompt,
            temperature=config.temperature,
        )
    except Exception as exc:
        # Czytelniejsza diagnoza (np. 400: zły format)
        raise ASRError(f"OpenAI transcription failed: {exc}") from exc

    text = getattr(response, "text", None) or ""
    lang_out = getattr(response, "language", None) or (language or "") or ""
    return Transcript(
        text=text.strip(),
        language=lang_out,
        raw=response.to_dict() if hasattr(response, "to_dict") else response,
    )


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
