"""File-mode capture and optional private PCM recording; no eager device start."""

from __future__ import annotations

import math
import secrets
import subprocess
import time
import wave

from common.secure_files import atomic_write

from .audio.capture import AudioCapture, CaptureError
from .vad import collect


class FileCaptureMixin:
    def _record_with_vad(self) -> bytes:
        now = time.time()
        if now < self._mute_until_ts:
            time.sleep(self._mute_until_ts - now)

        audio = b""
        try:
            with AudioCapture(self._capture_cfg, self.logger) as capture:
                if self._mic_open_delay_ms > 0:
                    time.sleep(self._mic_open_delay_ms / 1000.0)

                frames_iter = capture.frames()

                # okno „no-cost”
                voiced = False
                start_wait = time.time()
                pre_buf: list[bytes] = []
                max_wait_s = max(0, self._no_speech_timeout_ms) / 1000.0
                while (time.time() - start_wait) < max_wait_s:
                    try:
                        f = next(frames_iter)
                    except StopIteration:
                        break
                    pre_buf.append(f)
                    if self._frame_has_voice(f, self._silence_rms_gate):
                        voiced = True
                        break
                if not voiced:
                    self.logger.event("service.nospeech.timeout", ms=self._no_speech_timeout_ms)
                    return b""

                # pre-roll
                need_frames = max(
                    1,
                    int(math.ceil(self._pre_speech_wait_ms / self._capture_cfg.frame_ms)),
                )
                while len(pre_buf) < need_frames:
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

                audio = collect(_chained(), self._vad, self._max_len)

        except CaptureError as exc:
            self.logger.event("service.capture.error", error=str(exc))
        except Exception as exc:
            self.logger.event("service.capture.unexpected", error=str(exc))

        # Minimalna długość
        min_ms = max(200, self._min_capture_ms)
        bytes_per_sample = 2  # 16-bit
        channels = max(1, int(getattr(self._capture_cfg, "channels", 1)))
        expected_min = int(self._capture_cfg.sample_rate * (min_ms / 1000.0)) * bytes_per_sample * channels

        if not audio:
            self.logger.event("service.capture.empty_retry_arecord")
            return self._record_with_arecord()

        if len(audio) < expected_min:
            self.logger.event(
                "service.capture.retry_short_clip",
                bytes=len(audio),
                threshold=expected_min,
            )
            try:
                with AudioCapture(self._capture_cfg, self.logger) as capture:
                    if self._mic_open_delay_ms > 0:
                        time.sleep(self._mic_open_delay_ms / 1000.0)
                    t0 = time.time()
                    chunks: list[bytes] = []
                    for f in capture.frames():
                        chunks.append(f)
                        if (time.time() - t0) >= 0.8:
                            break
                    audio2 = collect(iter(chunks), self._vad, self._max_len)
                    if audio2 and len(audio2) > len(audio):
                        audio = audio2
            except Exception as exc:
                self.logger.event("service.capture.retry_error", error=str(exc))

            if len(audio) < expected_min:
                self.logger.event(
                    "service.capture.fast_fail.too_short",
                    bytes=len(audio),
                    threshold=expected_min,
                )
                return b""

        return audio

    def _record_with_arecord(self) -> bytes:
        cfg = self._capture_cfg
        device = cfg.device or "plughw:1,0"
        buffer_seconds = float(getattr(cfg, "buffer_seconds", 0) or 0.0)

        # arecord -d: całe sekundy → max 4 s, min 2 s
        duration_float = max(self._max_len / 1000.0, 1.0) + buffer_seconds + 0.5
        duration_s = int(math.ceil(duration_float))
        duration_s = max(2, min(4, duration_s))

        cmd = [
            "arecord",
            "-q",
            "-t",
            "raw",
            "-f",
            "S16_LE",
            "-c",
            str(max(1, int(cfg.channels))),
            "-r",
            str(cfg.sample_rate),
            "-D",
            device,
            "-d",
            str(duration_s),
        ]

        buffer_us = int(max(0.0, buffer_seconds) * 1_000_000)
        if buffer_us > 0:
            cmd += ["--buffer-time", str(buffer_us)]

        self.logger.event("service.capture.fallback.start", command=" ".join(cmd))
        try:
            proc = subprocess.run(cmd, capture_output=True, check=False)
        except FileNotFoundError:
            self.logger.event("service.capture.arecord_missing")
            return b""
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", "ignore").strip()
            self.logger.event(
                "service.capture.arecord_failed",
                returncode=proc.returncode,
                stderr=stderr,
            )
            return b""
        raw = proc.stdout or b""
        if not raw:
            self.logger.event("service.capture.arecord_empty")
            return b""

        frames = self._frames_from_pcm(raw, self._safe_frame_bytes())
        trimmed = collect(frames, self._vad, self._max_len)

        min_ms = max(200, self._min_capture_ms)
        bytes_per_sample = 2
        channels = max(1, int(getattr(self._capture_cfg, "channels", 1)))
        expected_min = int(self._capture_cfg.sample_rate * (min_ms / 1000.0)) * bytes_per_sample * channels

        if trimmed:
            if len(trimmed) >= expected_min:
                self.logger.event(
                    "service.capture.fallback.success",
                    backend="arecord",
                    bytes=len(trimmed),
                )
                return trimmed
            if len(raw) >= max(1, expected_min // 2):
                self.logger.event(
                    "service.capture.fallback.trimmed_too_short_using_raw",
                    bytes_trimmed=len(trimmed),
                    bytes_raw=len(raw),
                )
                return raw
            self.logger.event(
                "service.capture.fallback.trimmed_too_short",
                bytes_trimmed=len(trimmed),
                bytes_required=expected_min,
            )
            return b""

        if len(raw) >= max(1, expected_min // 2):
            self.logger.event("service.capture.fallback.no_vad_using_raw", bytes=len(raw))
            return raw

        self.logger.event("service.capture.fallback.no_vad")
        return b""

    def _frames_from_pcm(self, data: bytes, frame_size: int):
        for off in range(0, len(data), frame_size):
            chunk = data[off : off + frame_size]
            if len(chunk) < frame_size:
                break
            yield chunk

    def _save_pcm(self, audio: bytes) -> None:
        filename = f"capture_{time.time_ns()}_{secrets.token_hex(8)}.wav"
        path = self._recordings_dir / filename

        def write(stream):
            with wave.open(stream, "wb") as wf:
                wf.setnchannels(max(1, int(getattr(self._capture_cfg, "channels", 1))))
                wf.setsampwidth(2)
                wf.setframerate(self._capture_cfg.sample_rate)
                wf.writeframes(audio)

        atomic_write(path, write, private=True, replace=False)
        self.logger.event("service.audio.saved", path=str(path))
