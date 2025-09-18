"""Keyword spotting and hotword helpers."""
from __future__ import annotations

import contextlib
import os
import threading
import time
from dataclasses import dataclass

from . import logging as voice_logging

try:
    from libnyumaya import AudioRecognition, FeatureExtractor  # type: ignore

    _HAS_NYUMAYA = True
except Exception:  # pragma: no cover - optional dependency
    AudioRecognition = None
    FeatureExtractor = None
    _HAS_NYUMAYA = False

try:  # pragma: no cover - optional dependency
    import pvporcupine  # type: ignore

    _HAS_PORCUPINE = True
except Exception:
    pvporcupine = None
    _HAS_PORCUPINE = False


@dataclass
class HotwordConfig:
    enabled: bool
    engine: str
    model: str | None = None
    library: str | None = None
    sensitivity: float = 0.6
    auto_gain: float = 1.0
    threshold: float = 0.6


class HotwordDetector:
    def __init__(self, config: HotwordConfig, logger: voice_logging.VoiceLogger | None = None):
        self.config = config
        self.logger = logger or voice_logging.get_logger("voice.hotword")
        self._mode = (config.engine or "off").lower()
        if not config.enabled:
            self._mode = "off"
        self._stop = threading.Event()
        self._nyumaya = None
        self._porcupine = None
        if self._mode == "nyumaya" and _HAS_NYUMAYA and config.model:
            library = config.library or os.environ.get("HOTWORD_LIB_PATH")
            try:
                extractor = FeatureExtractor(library)
                detector = AudioRecognition(library)
                keyword_id = detector.addModel(config.model, config.sensitivity)
                frame_size = detector.getInputDataSize()
                self._nyumaya = (extractor, detector, keyword_id, frame_size)
                self.logger.event("hotword.nyumaya", model=config.model, frame_size=frame_size)
            except Exception as exc:
                self.logger.error("hotword.nyumaya_failed", error=str(exc))
                self._mode = "off"
        elif self._mode == "porcupine" and _HAS_PORCUPINE and config.model:
            try:
                self._porcupine = pvporcupine.create(keyword_paths=[config.model], sensitivities=[config.sensitivity])
                self.logger.event("hotword.porcupine", model=config.model)
            except Exception as exc:
                self.logger.error("hotword.porcupine_failed", error=str(exc))
                self._mode = "off"
        elif self._mode in {"nyumaya", "porcupine"}:
            self.logger.warning("hotword.backend_unavailable", engine=self._mode)
            self._mode = "off"

    def stop(self) -> None:
        self._stop.set()
        if self._porcupine:
            with contextlib.suppress(Exception):  # type: ignore[name-defined]
                self._porcupine.delete()

    def wait(self, capture, timeout: float | None = None) -> bool:
        """Block until the hotword is detected or timeout occurs."""

        start = time.time()
        if self._mode in {"off", "none"}:
            return True
        if self._mode == "ptt":
            input("[voice] Press ENTER to speak…")
            return True
        if self._mode == "nyumaya" and self._nyumaya:
            return self._wait_nyumaya(capture, timeout, start)
        if self._mode == "porcupine" and self._porcupine:
            return self._wait_porcupine(capture, timeout, start)
        return True

    def _wait_nyumaya(self, capture, timeout: float | None, start: float) -> bool:
        extractor, detector, keyword_id, frame_size = self._nyumaya
        while not self._stop.is_set():
            if timeout and time.time() - start > timeout:
                return False
            frame = capture.read(frame_size * 2)
            if not frame:
                time.sleep(0.01)
                continue
            features = extractor.signalToMel(frame, self.config.auto_gain)
            prediction = detector.runDetection(features)
            if prediction == keyword_id:
                self.logger.event("hotword.trigger", engine="nyumaya")
                return True
        return False

    def _wait_porcupine(self, capture, timeout: float | None, start: float) -> bool:
        porcupine = self._porcupine
        frame_length = porcupine.frame_length
        while not self._stop.is_set():
            if timeout and time.time() - start > timeout:
                return False
            data = capture.read(frame_length * 2)
            if not data:
                time.sleep(0.01)
                continue
            pcm = [int.from_bytes(data[i : i + 2], "little", signed=True) for i in range(0, len(data), 2)]
            result = porcupine.process(pcm)
            if result >= 0:
                self.logger.event("hotword.trigger", engine="porcupine")
                return True
        return False


def disabled() -> HotwordDetector:
    return HotwordDetector(HotwordConfig(enabled=False, engine="off"))
