# apps/voice/vad.py
"""Voice activity detection helpers."""

from __future__ import annotations

import collections
import math
from collections.abc import Callable, Iterable

try:
    import webrtcvad  # type: ignore

    _HAS_WEBRTC = True
except Exception:  # pragma: no cover - optional dependency
    webrtcvad = None  # type: ignore
    _HAS_WEBRTC = False

FrameHandler = Callable[[bytes], bool]


def rms_dbfs(frame: bytes) -> float:
    """
    Szacunek RMS w dBFS dla S16_LE.
    Zwraca ~[-100..0]; 0 dBFS to 32767 (szczyt).
    """
    if not frame:
        return -100.0
    # 16-bit little-endian, mono/stereo bez znaczenia dla RMS (liczymy po próbkach)
    samples = [int.from_bytes(frame[i : i + 2], "little", signed=True) for i in range(0, len(frame), 2)]
    if not samples:
        return -100.0
    # energia = średnia z kwadratów amplitud
    energy = sum(s * s for s in samples) / float(len(samples))
    if energy <= 0:
        return -100.0
    # dBFS(RMS) = 10*log10(energy / 32768^2)
    return 10.0 * math.log10(energy / float(32768 * 32768))


class SilenceTail:
    """
    Prosty wykrywacz końca mowy: gdy w oknie `tail_ms` nie pojawia się mowa → True (stop).
    """

    def __init__(self, frame_ms: int, tail_ms: int):
        frame_ms = max(5, int(frame_ms or 20))
        tail_ms = max(0, int(tail_ms or 0))
        self.frame_ms = frame_ms
        self.limit = max(1, tail_ms // frame_ms)
        self.window = collections.deque(maxlen=self.limit)

    def push(self, is_speech: bool) -> bool:
        """
        Dodaj decyzję dla bieżącej ramki.
        :param is_speech: True jeśli mowa, False jeśli cisza
        :return: True gdy okno zawiera wyłącznie ciszę (koniec mowy).
        """
        if self.limit <= 1:
            # specjalny przypadek: brak ogona → stop po jednej cichej ramce
            return not is_speech
        self.window.append(is_speech)
        if len(self.window) < self.window.maxlen:
            return False
        return not any(self.window)

    def reset(self) -> None:
        """Wyczyść okno ciszy (reset stanu między nagraniami)."""
        self.window.clear()


class WebRtcActivity:
    """
    Detektor aktywności mowy:
    - gdy dostępny `webrtcvad`, używa go (wymaga ramek 10/20/30 ms @ 8/16/32/48 kHz, S16_LE mono),
    - w przeciwnym razie fallback: bramka energetyczna + ogon ciszy.

    Wywołanie zwraca **True, gdy wykryto koniec mowy** (czyli „można kończyć nagrywanie”).
    """

    def __init__(self, sample_rate: int, mode: int, frame_ms: int, tail_ms: int, energy_gate: float = -40.0):
        self.sample_rate = int(sample_rate or 16000)
        # WebRTC akceptuje 10/20/30 ms; resztę „przycinamy” do najbliższej z tych wartości
        if frame_ms not in (10, 20, 30):
            frame_ms = min((10, 20, 30), key=lambda v: abs(v - (frame_ms or 20)))
        self.frame_ms = int(frame_ms)
        self.tail = SilenceTail(self.frame_ms, int(tail_ms or 700))
        self.energy_gate = float(energy_gate)
        self._vad = webrtcvad.Vad(int(mode)) if _HAS_WEBRTC else None

    def _is_speech_energy(self, frame: bytes) -> bool:
        """Fallback: tylko na podstawie dBFS."""
        return rms_dbfs(frame) >= self.energy_gate

    def __call__(self, frame: bytes) -> bool:
        """
        :param frame: bajty S16_LE (mono); przy stereo też zadziała heurystycznie
        :return: True, gdy spełniono kryterium końca mowy (okno ciszy)
        """
        if not frame:
            return False

        if self._vad is None:
            # Fallback: decyzja z progu energetycznego
            is_speech = self._is_speech_energy(frame)
            return self.tail.push(is_speech)

        # Bramka energetyczna przed webrtcvad – odfiltruj szum bardzo cichy
        if rms_dbfs(frame) < self.energy_gate:
            is_speech = False
        else:
            try:
                is_speech = self._vad.is_speech(frame, self.sample_rate)
            except Exception:
                # W razie błędu biblioteki – nie przerywaj, użyj progu
                is_speech = self._is_speech_energy(frame)

        return self.tail.push(is_speech)

    def reset(self) -> None:
        """Resetuj stan VAD/taila przed nowym nagraniem."""
        self.tail.reset()


def collect(stream: Iterable[bytes], detector: WebRtcActivity, max_len_ms: int) -> bytes:
    """
    Zbierz strumień ramek do momentu:
    - wykrycia końca mowy (detector(...) -> True), lub
    - przekroczenia maksymalnej długości `max_len_ms`.

    Zakładamy, że każda ramka reprezentuje `detector.frame_ms` milisekund.
    """
    frames: list[bytes] = []
    collected_ms = 0
    for chunk in stream:
        if not chunk:
            continue
        frames.append(chunk)
        collected_ms += detector.frame_ms
        try:
            stop = detector(chunk)
        except Exception:
            # VAD nie może zepsuć nagrania — w razie błędu po prostu kontynuuj
            stop = False
        if stop:
            break
        if collected_ms >= int(max_len_ms or 0):
            break
    return b"".join(frames)
