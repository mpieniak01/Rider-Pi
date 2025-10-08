# apps/voice/svc_stream.py
"""WebSocket streaming voice service - compatibility shim/router.

This module serves as a compatibility layer that re-exports the refactored
StreamingVoiceService from apps.voice.stream.service, while maintaining the
CLI wrapper functions (run_once_stream, run_listen_stream, run_ptt_stream)
for backward compatibility with existing tests and command-line interfaces.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from typing import Any

# Re-export for test compatibility
from .playback import play_ding  # noqa: F401

# Re-export the refactored streaming service and config
from .stream.service import StreamConfig, StreamingVoiceService  # noqa: F401


# ────────────────────────────────────────────────────────────────────────────
# PROXY/Wrappers dla CLI i testów
# ────────────────────────────────────────────────────────────────────────────
def _run_coro_in_thread(coro) -> Any:
    """Uruchom coroutine w osobnym wątku z własną pętlą (bez kolizji z @pytest.mark.asyncio)."""
    result_box: dict[str, Any] = {}
    error_box: dict[str, BaseException] = {}

    def _target():
        try:
            result_box["r"] = asyncio.run(coro)
        except BaseException as e:  # noqa: BLE001
            error_box["e"] = e

    t = threading.Thread(target=_target, name="svc-stream-proxy", daemon=True)
    t.start()
    t.join()
    if "e" in error_box:
        raise error_box["e"]
    return result_box.get("r")


def run_once_stream(cfg: dict[str, Any], args) -> int:
    """Run streaming once mode (CLI/test proxy)."""
    service = StreamingVoiceService(cfg)
    try:
        # once() jest synchroniczne (wywołuje asyncio.run wewnątrz),
        # but testowy DummyService.once() może być async → obsłuż oba przypadki.
        ret = service.once()
        if inspect.iscoroutine(ret):
            result = _run_coro_in_thread(ret)
        else:
            result = ret

        if isinstance(result, dict) and result.get("transcript", {}).get("text"):
            print(result["transcript"]["text"])  # noqa: T201
        return 0
    finally:
        stop = getattr(service, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass


def run_listen_stream(cfg: dict[str, Any], args) -> int:
    """Start streaming in 'listen' mode (CLI/test proxy)."""
    service = StreamingVoiceService(cfg)
    try:
        # listen() może być synchroniczne lub async – obsłuż oba przypadki
        ret = service.listen()
        if inspect.iscoroutine(ret):
            _run_coro_in_thread(ret)  # DummyService.listen() jest async w teście
        return 0
    finally:
        stop = getattr(service, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass


def run_ptt_stream(cfg: dict[str, Any], args) -> int:
    """PTT: włącz hotword.enabled i deleguj do run_listen_stream (test patchuje ten symbol)."""
    cfg2 = dict(cfg) if cfg else {}
    hot = dict(cfg2.get("hotword", {}))
    hot["enabled"] = True
    hot["engine"] = "ptt"
    cfg2["hotword"] = hot
    return run_listen_stream(cfg2, args)
