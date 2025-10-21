# apps/voice/local_io.py
# Rider-Pi: lokalny backend głosowy (TTS Piper + ASR Vosk)
from __future__ import annotations

import io
import json
import wave
from dataclasses import dataclass

# TTS (Piper)
try:
    # pip install piper-tts
    import piper  # type: ignore

    _PIPER_OK = True
except Exception:
    _PIPER_OK = False

# ASR (Vosk)
try:
    # pip install vosk
    from vosk import KaldiRecognizer, Model  # type: ignore

    _VOSK_OK = True
except Exception:
    _VOSK_OK = False


@dataclass
class PiperConfig:
    model_path: str
    speaker: int | None = None
    length_scale: float = 1.0
    noise_scale: float = 0.667
    noise_w: float = 0.8
    sample_rate: int = 22050  # Piper zwykle generuje 22.05 kHz


@dataclass
class VoskConfig:
    model_path: str
    sample_rate: int = 16000


class LocalTTS:
    """Lekki wrapper na Piper – generuje WAV w pamięci."""

    def __init__(self, cfg: PiperConfig):
        if not _PIPER_OK:
            raise RuntimeError("piper module not available (pip install piper-tts)")
        self.cfg = cfg
        self._tts = piper.PiperVoice(cfg.model_path)

    def synth_wav(self, text: str) -> bytes:
        if not text:
            text = "Brak treści."
        # piper generuje PCM 16-bit LE; zapiszmy jako prawidłowy WAV
        pcm = self._tts.synthesize(
            text,
            speaker_id=self.cfg.speaker,
            length_scale=self.cfg.length_scale,
            noise_scale=self.cfg.noise_scale,
            noise_w=self.cfg.noise_w,
        )
        return _pcm16_to_wav_bytes(pcm, self.cfg.sample_rate, channels=1)


class LocalASR:
    """Lekki wrapper na Vosk – rozpoznaje z WAV/PCM."""

    def __init__(self, cfg: VoskConfig):
        if not _VOSK_OK:
            raise RuntimeError("vosk module not available (pip install vosk)")
        self.cfg = cfg
        self._model = Model(cfg.model_path)

    def from_wav(self, wav_bytes: bytes) -> dict:
        """Przyjmij WAV (mono/16k) lub inne – wymusimy resample tylko jeśli trzeba."""
        # Minimalna walidacja nagłówka WAV:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            nch = w.getnchannels()
            rate = w.getframerate()
            sampwidth = w.getsampwidth()
            frames = w.getnframes()
            pcm = w.readframes(frames)
        if sampwidth != 2:
            raise ValueError("Oczekiwany 16-bit PCM (sampwidth=2)")
        if nch != 1:
            # Vosk najlepiej mono – prosty downmix (L)
            pcm = _downmix_to_mono(pcm, sampwidth, nch)

        if rate != self.cfg.sample_rate:
            # Bez zewn. zależności nie resamplujemy – sygnalizujemy błąd jasno
            raise ValueError(f"Oczekiwane {self.cfg.sample_rate} Hz, otrzymano {rate} Hz")

        rec = KaldiRecognizer(self._model, self.cfg.sample_rate)
        rec.AcceptWaveform(pcm)
        try:
            data = json.loads(rec.FinalResult() or "{}")
        except Exception:
            data = {"text": ""}
        return {"ok": True, "text": data.get("text", "").strip()}


def _pcm16_to_wav_bytes(pcm: bytes, sr: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


def _downmix_to_mono(pcm: bytes, sampwidth: int, nch: int) -> bytes:
    # szybki downmix: bierz pierwszy kanał (bez sumowania)
    if sampwidth != 2:
        return pcm
    import array

    arr = array.array("h")
    arr.frombytes(pcm)
    # arr: [L0, R0, L1, R1, ...] -> wybierz tylko L
    mono = arr[0::nch]
    return mono.tobytes()
