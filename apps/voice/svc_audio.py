# apps/voice/svc_audio.py
"""Voice service audio I/O adapter - ALSA, capture, playback, ding."""

from __future__ import annotations

import audioop  # <-- konwersje szerokości próbek
import math
import subprocess
import time
from collections.abc import Iterator
from typing import Any

from .audio.capture import AudioCapture, CaptureConfig, CaptureError
from .audio.playback import PlaybackConfig, play_ding as playback_play_ding
from .vad import WebRtcActivity, collect


def ensure_mono_16k(audio_data: bytes, capture_cfg: CaptureConfig) -> bytes:
    """Zapewnij MONO @16k S16_LE na wyjściu (bez resamplingu).

    Wejście: surowe PCM z capture (S16_LE, interleaved kanały).
    Jeśli `channels==1` — zwraca bufor bez zmian.
    Jeśli `channels>=2` — bezpieczny downmix przez audioop.tomono(..., width=2).
    Uwaga: funkcja NIE robi resamplingu — sample_rate=16000 powinien być ustawiony w config/CLI.
    """
    if not audio_data:
        return audio_data

    try:
        channels = int(getattr(capture_cfg, "channels", 1) or 1)
    except Exception:
        channels = 1

    if channels <= 1:
        return audio_data

    try:
        # width=2 (S16_LE); miks 50/50 zmniejsza ryzyko przesteru
        return audioop.tomono(audio_data, 2, 0.5, 0.5)
    except Exception:
        # Gdyby coś poszło nie tak po stronie audioop — oddaj oryginał (lepsze niż korupcja danych)
        return audio_data


def capture_once(
    capture_cfg: CaptureConfig,
    vad: WebRtcActivity,
    max_len_ms: int,
    service_cfg: dict[str, Any],
    logger,
) -> bytes:
    """Capture audio @16kHz mono; returns bytes for transcribe_file()."""
    # Get timing parameters from service config
    mic_open_delay_ms = int(service_cfg.get("mic_open_delay_ms", 100))
    pre_speech_wait_ms = int(service_cfg.get("pre_speech_wait_ms", 1000))
    min_capture_ms = int(service_cfg.get("min_capture_ms", 1000))

    audio = b""
    try:
        with AudioCapture(capture_cfg, logger) as capture:
            if mic_open_delay_ms > 0:
                time.sleep(mic_open_delay_ms / 1000.0)

            frames_iter = capture.frames()

            # Pre-roll: require at least pre_speech_wait_ms before allowing VAD to end
            pre_frames_needed = max(1, int(math.ceil(pre_speech_wait_ms / capture_cfg.frame_ms)))
            pre_buf: list[bytes] = []
            for _ in range(pre_frames_needed):
                try:
                    pre_buf.append(next(frames_iter))
                except StopIteration:
                    break

            # If we collected little (eg slow start), collect up to 0.6s more
            if len(pre_buf) < pre_frames_needed // 4:
                t0 = time.time()
                while len(pre_buf) < pre_frames_needed and (time.time() - t0) < 0.6:
                    try:
                        pre_buf.append(next(frames_iter))
                    except StopIteration:
                        break

            def _chained():
                for f in pre_buf:
                    if f:
                        yield f
                for f in frames_iter:
                    yield f

            audio = collect(_chained(), vad, max_len_ms)

    except CaptureError as exc:
        logger.event("service.capture.error", error=str(exc))
    except Exception as exc:
        logger.event("service.capture.unexpected", error=str(exc))

    # Minimum length check for entire clip
    min_ms = max(200, min_capture_ms)
    bytes_per_sample = 2  # 16-bit
    channels = max(1, int(getattr(capture_cfg, "channels", 1)))
    expected_min = int(capture_cfg.sample_rate * (min_ms / 1000.0)) * bytes_per_sample * channels

    # Nothing captured -> fallback to arecord
    if not audio:
        logger.debug("service.capture.empty_retry_arecord")
        return capture_with_arecord(capture_cfg, vad, max_len_ms, logger, min_capture_ms)

    # Too short -> short retry (~0.8s) and try again on collected buffer
    if len(audio) < expected_min:
        logger.event("service.capture.retry_short_clip", bytes=len(audio), threshold=expected_min)
        try:
            with AudioCapture(capture_cfg, logger) as capture:
                if mic_open_delay_ms > 0:
                    time.sleep(mic_open_delay_ms / 1000.0)
                t0 = time.time()
                chunks: list[bytes] = []
                for f in capture.frames():
                    chunks.append(f)
                    if (time.time() - t0) >= 0.8:
                        break
                audio2 = collect(iter(chunks), vad, max_len_ms)
                if audio2 and len(audio2) > len(audio):
                    audio = audio2
        except Exception as exc:
            logger.event("service.capture.retry_error", error=str(exc))

        if len(audio) < expected_min:
            logger.event(
                "service.capture.fast_fail.too_short",
                bytes=len(audio),
                threshold=expected_min,
            )
            return b""

    return audio


def capture_with_arecord(
    capture_cfg: CaptureConfig,
    vad: WebRtcActivity,
    max_len_ms: int,
    logger,
    min_capture_ms: int,
) -> bytes:
    """Fallback capture using arecord command (S32_LE -> konwersja do S16_LE)."""
    device = capture_cfg.device or "plughw:1,0"
    buffer_seconds = float(getattr(capture_cfg, "buffer_seconds", 0) or 0.0)
    sample_format = str(getattr(capture_cfg, "sample_format", "S16_LE")).upper()
    channels = max(1, int(getattr(capture_cfg, "channels", 1)))
    sample_rate = int(getattr(capture_cfg, "sample_rate", 16000))

    # arecord -d wymaga pełnych sekund → limit 2..4 s
    duration_float = max(max_len_ms / 1000.0, 1.0) + buffer_seconds + 0.5
    duration_s = int(math.ceil(duration_float))
    duration_s = max(2, min(4, duration_s))

    cmd = [
        "arecord",
        "-q",
        "-t",
        "raw",
        "-f",
        sample_format,  # respektuj format karty (np. S32_LE)
        "-c",
        str(channels),
        "-r",
        str(sample_rate),
        "-D",
        device,
        "-d",
        str(duration_s),
    ]

    buffer_us = int(max(0.0, buffer_seconds) * 1_000_000)
    if buffer_us > 0:
        cmd += ["--buffer-time", str(buffer_us)]

    logger.event("service.capture.fallback.start", command=" ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False)
    except FileNotFoundError:
        logger.error("service.capture.arecord_missing")
        return b""

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "ignore").strip()
        logger.event("service.capture.arecord_failed", returncode=proc.returncode, stderr=stderr)
        return b""

    raw_in = proc.stdout or b""
    if not raw_in:
        logger.warning("service.capture.arecord_empty")
        return b""

    # --- KONWERSJA DO 16-bit LE (jeśli nagrano S32_LE) ---
    in_width = 4 if sample_format.startswith("S32") else 2
    try:
        raw_s16 = audioop.lin2lin(raw_in, in_width, 2) if in_width != 2 else raw_in
    except Exception as exc:
        logger.event("service.capture.convert_failed", error=str(exc))
        return b""

    # Podziel na ramki 16-bit do VAD
    frame_ms = int(getattr(capture_cfg, "frame_ms", 20))
    frame_bytes_16 = int(sample_rate * (frame_ms / 1000.0)) * 2 * channels

    frames = _frames_from_pcm(raw_s16, frame_bytes_16)
    trimmed = collect(frames, vad, max_len_ms)

    # Minimum length
    min_ms = max(200, min_capture_ms)
    expected_min = int(sample_rate * (min_ms / 1000.0)) * 2 * channels

    if trimmed:
        if len(trimmed) >= expected_min:
            logger.event(
                "service.capture.fallback.success",
                backend="arecord",
                bytes=len(trimmed),
            )
            return trimmed
        if len(raw_s16) >= max(1, expected_min // 2):
            logger.event(
                "service.capture.fallback.trimmed_too_short_using_raw",
                bytes_trimmed=len(trimmed),
                bytes_raw=len(raw_s16),
            )
            return raw_s16
        logger.event(
            "service.capture.fallback.trimmed_too_short",
            bytes_trimmed=len(trimmed),
            bytes_required=expected_min,
        )
        return b""

    if len(raw_s16) >= max(1, expected_min // 2):
        logger.event("service.capture.fallback.no_vad_using_raw", bytes=len(raw_s16))
        return raw_s16

    logger.warning("service.capture.fallback.no_vad")
    return b""


def _frames_from_pcm(data: bytes, frame_size: int) -> Iterator[bytes]:
    """Split PCM data into frames."""
    for off in range(0, len(data), frame_size):
        chunk = data[off : off + frame_size]
        if len(chunk) < frame_size:
            break
        yield chunk


def playback_tts(cfg: dict[str, Any], audio_bytes: bytes) -> None:
    """Play TTS result; respects volume and post_tts_mute_ms.

    Placeholder – odtwarzanie TTS jest obsługiwane przez warstwę „speech worker”.
    """
    return None


def capture_continuous(capture_cfg: dict[str, Any], chunk_size: int) -> Iterator[bytes]:
    """Generator, który zwraca kolejne porcje audio do streamingu.

    Nie stosuje fallbacku na arecord (streaming ma działać na głównym backendzie).
    Downmix do MONO realizujemy po stronie `svc_stream` (nadawczej) przez `ensure_mono_16k`.
    """
    config = CaptureConfig(
        backend=capture_cfg.get("backend", "alsa"),
        device=capture_cfg.get("device", "plughw:wm8960soundcard,0"),
        sample_rate=int(capture_cfg.get("sample_rate", 16000)),
        channels=int(capture_cfg.get("channels", 1)),
        frame_ms=int(capture_cfg.get("frame_ms", 20)),
        buffer_seconds=float(capture_cfg.get("buffer_seconds", 0.1)),
        # Jeśli moduł .capture obsługuje sample_format, przekaż dalej:
        sample_format=str(capture_cfg.get("sample_format", capture_cfg.get("format", "S16_LE"))).upper(),
    )

    try:
        # Uwaga: AudioCapture może wymagać loggera (w tej wersji przyjmujemy, że jest opcjonalny).
        with AudioCapture(config) as capture:
            buffer = b""
            for frame in capture.frames():
                if not frame:
                    continue
                buffer += frame
                while len(buffer) >= chunk_size:
                    yield buffer[:chunk_size]
                    buffer = buffer[chunk_size:]
    except Exception:
        # Fallback do arecord robimy tylko w ścieżce capture_once(); w streamingu nie.
        return


def play_ding(cfg: dict[str, Any], logger) -> None:
    """Zagraj ding (ustawienia: gain_db, beep_pause_ms) przez backend playback."""
    playback_cfg = cfg.get("playback", {})
    play_cfg = PlaybackConfig(**playback_cfg)
    playback_play_ding(play_cfg, logger)
