"""Text-to-speech backends."""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import wave
from dataclasses import dataclass

import requests

from . import logging as voice_logging


class TTSError(RuntimeError):
    pass


@dataclass
class TTSConfig:
    backend: str
    model: str
    voice: str
    format: str = "wav"
    piper_model: str | None = None
    piper_config: str | None = None


def synthesize(text: str, config: TTSConfig, logger: voice_logging.VoiceLogger | None = None) -> tuple[bytes, int, str]:
    backend = (config.backend or "openai").lower()
    logger = logger or voice_logging.get_logger("voice.tts")
    if backend == "openai":
        return _tts_openai(text, config, logger)
    if backend == "piper":
        return _tts_piper(text, config, logger)
    raise TTSError(f"Unsupported TTS backend: {backend}")


def _tts_openai(text: str, config: TTSConfig, logger: voice_logging.VoiceLogger) -> tuple[bytes, int, str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise TTSError("OPENAI_API_KEY not configured")
    url = "https://api.openai.com/v1/audio/speech"
    payload = {
        "model": config.model,
        "voice": config.voice,
        "input": text,
        "format": config.format,
    }
    resp = requests.post(url, json=payload, timeout=60)
    if resp.status_code >= 400:
        raise TTSError(f"OpenAI TTS error: {resp.status_code} {resp.text}")
    audio = resp.content
    sample_rate = 0
    if config.format == "wav":
        with wave.open(io.BytesIO(audio)) as wf:  # type: ignore[arg-type]
            sample_rate = wf.getframerate()
    logger.event("tts.openai", format=config.format)
    return audio, sample_rate, config.format


def _tts_piper(text: str, config: TTSConfig, logger: voice_logging.VoiceLogger) -> tuple[bytes, int, str]:
    if not config.piper_model:
        raise TTSError("piper_model not configured")
    output = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    output.close()
    cmd = [
        "piper",
        "--model",
        config.piper_model,
        "--output_file",
        output.name,
    ]
    if config.piper_config:
        cmd += ["--config", config.piper_config]
    try:
        subprocess.run(cmd, input=text.encode("utf-8"), check=True)
        with open(output.name, "rb") as fh:
            audio = fh.read()
        with wave.open(output.name) as wf:
            sample_rate = wf.getframerate()
    except FileNotFoundError as exc:
        raise TTSError("piper executable not found") from exc
    except subprocess.CalledProcessError as exc:
        raise TTSError(f"Piper failed: {exc}") from exc
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(output.name)
    logger.event("tts.piper", sample_rate=sample_rate)
    return audio, sample_rate, "wav"
