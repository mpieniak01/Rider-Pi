"""Voice activity detection helpers."""

from __future__ import annotations

import collections
import math
from collections.abc import Callable

try:
    import webrtcvad  # type: ignore

    _HAS_WEBRTC = True
except Exception:  # pragma: no cover - optional dependency
    webrtcvad = None
    _HAS_WEBRTC = False

FrameHandler = Callable[[bytes], bool]


def rms_dbfs(frame: bytes) -> float:
    if not frame:
        return -100.0
    samples = [int.from_bytes(frame[i : i + 2], "little", signed=True) for i in range(0, len(frame), 2)]
    energy = sum(s * s for s in samples) / max(len(samples), 1)
    if energy <= 0:
        return -100.0
    return 10 * math.log10(energy / (2**31))


class SilenceTail:
    def __init__(self, frame_ms: int, tail_ms: int):
        self.limit = max(1, tail_ms // frame_ms)
        self.window = collections.deque(maxlen=self.limit)

    def push(self, is_speech: bool) -> bool:
        self.window.append(is_speech)
        if len(self.window) < self.window.maxlen:
            return False
        return not any(self.window)


class WebRtcActivity:
    def __init__(self, sample_rate: int, mode: int, frame_ms: int, tail_ms: int, energy_gate: float = -40.0):
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.tail = SilenceTail(frame_ms, tail_ms)
        self.energy_gate = energy_gate
        self._vad = webrtcvad.Vad(mode) if _HAS_WEBRTC else None

    def __call__(self, frame: bytes) -> bool:
        if not frame:
            return False
        if self._vad is None:
            return False
        if rms_dbfs(frame) < self.energy_gate:
            decision = False
        else:
            decision = self._vad.is_speech(frame, self.sample_rate)
        return self.tail.push(not decision)


def collect(stream, detector: WebRtcActivity, max_len_ms: int) -> bytes:
    frames = []
    collected = 0
    for chunk in stream:
        frames.append(chunk)
        collected += detector.frame_ms
        stop = detector(chunk)
        if stop:
            break
        if collected >= max_len_ms:
            break
    return b"".join(frames)
