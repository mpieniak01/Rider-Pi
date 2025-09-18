"""Automatic speech recognition backends."""
from __future__ import annotations

import io
import json
import os
import wave
from dataclasses import dataclass
from typing import Any

from . import logging as voice_logging


class ASRError(RuntimeError):
    pass


@dataclass
class ASRConfig:
    backend: str
    model: str
    language: str | None
    temperature: float = 0.0
    prompt: str | None = None
    vosk_model_dir: str | None = None
    whisper_model: str | None = None
    input_encoding: str | None = None


@dataclass
class Transcript:
    text: str
    language: str
    raw: Any | None = None


def _pcm_to_wav_bytes(audio: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio)
    return buf.getvalue()


def transcribe(audio: bytes, sample_rate: int, config: ASRConfig, logger: voice_logging.VoiceLogger | None = None) -> Transcript:
    backend = (config.backend or "stub").lower()
    if backend == "openai":
        return _openai_transcribe(audio, sample_rate, config, logger or voice_logging.get_logger("voice.asr"))
    if backend == "vosk":
        return _vosk_transcribe(audio, sample_rate, config, logger or voice_logging.get_logger("voice.asr"))
    raise ASRError(f"Unsupported ASR backend: {backend}")


def _openai_transcribe(audio: bytes, sample_rate: int, config: ASRConfig, logger: voice_logging.VoiceLogger) -> Transcript:
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - optional dependency
        raise ASRError(f"OpenAI SDK unavailable: {exc}") from exc
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ASRError("OPENAI_API_KEY not configured")
    client = OpenAI(api_key=api_key)
    wav_bytes = _pcm_to_wav_bytes(audio, sample_rate)
    buffer = io.BytesIO(wav_bytes)
    buffer.name = "input.wav"
    response = client.audio.transcriptions.create(
        model=config.model,
        file=buffer,
        language=config.language,
        prompt=config.prompt,
        temperature=config.temperature,
    )
    text = getattr(response, "text", None) or ""
    language = getattr(response, "language", None) or config.language or ""
    return Transcript(text=text.strip(), language=language, raw=response.to_dict() if hasattr(response, "to_dict") else response)


def _vosk_transcribe(audio: bytes, sample_rate: int, config: ASRConfig, logger: voice_logging.VoiceLogger) -> Transcript:
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
    language = config.language or result.get("language", "") or ""
    return Transcript(text=text, language=language or "")
