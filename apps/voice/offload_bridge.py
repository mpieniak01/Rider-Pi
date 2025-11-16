"""Voice offload bridge - streams audio/text to Rider-PC when provider mode is 'pc'."""

from __future__ import annotations

import base64
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from common.bus import (
    TOPIC_VOICE_ASR_REQUEST,
    TOPIC_VOICE_ASR_RESULT,
    TOPIC_VOICE_TTS_CHUNK,
    BusPub,
    BusSub,
)


@dataclass
class VoiceOffloadBridge:
    """Minimal bridge that publishes PCM frames to PC and waits for ASR results."""

    topic_request: str = TOPIC_VOICE_ASR_REQUEST
    topic_response: str = TOPIC_VOICE_ASR_RESULT
    _pub: BusPub | None = None
    _sub: BusSub | None = None
    _tts_sub: BusSub | None = None
    _thread: threading.Thread | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _results: queue.Queue[dict[str, Any]] = field(default_factory=queue.Queue)
    _tts_chunks: queue.Queue[dict[str, Any]] = field(default_factory=queue.Queue)

    def start(self) -> None:
        if self._thread:
            return
        self._pub = BusPub()
        self._sub = BusSub(self.topic_response)
        self._tts_sub = BusSub(TOPIC_VOICE_TTS_CHUNK)
        self._thread = threading.Thread(target=self._recv_loop, name="voice-offload", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._sub:
            try:
                self._sub.close()
            except Exception:
                pass
            self._sub = None
        if self._tts_sub:
            try:
                self._tts_sub.close()
            except Exception:
                pass
            self._tts_sub = None
        if self._pub:
            try:
                self._pub.close()
            except Exception:
                pass
            self._pub = None

    def _recv_loop(self) -> None:
        subs = [s for s in (self._sub, self._tts_sub) if s is not None]
        if not subs:
            return
        while not self._stop.is_set():
            try:
                for subscriber in subs:
                    topic, payload = subscriber.recv(timeout_ms=100)
                    if topic and payload:
                        if topic == self.topic_response:
                            self._results.put(payload)
                        elif topic == TOPIC_VOICE_TTS_CHUNK:
                            self._tts_chunks.put(payload)
            except Exception:
                time.sleep(0.1)

    def publish_audio_chunk(self, pcm_bytes: bytes, rate: int, ts: float | None = None) -> None:
        if not self._pub:
            raise RuntimeError("offload bridge not started")
        payload = {
            "ts": ts or time.time(),
            "rate": rate,
            "len": len(pcm_bytes),
            "chunk_pcm": base64.b64encode(pcm_bytes).decode("ascii"),
        }
        self._pub.publish(self.topic_request, payload, add_ts=False)

    def iter_results(self) -> Iterable[dict[str, Any]]:
        while True:
            try:
                yield self._results.get_nowait()
            except queue.Empty:
                break

    def iter_tts_chunks(self) -> Iterable[dict[str, Any]]:
        while True:
            try:
                yield self._tts_chunks.get_nowait()
            except queue.Empty:
                break
