# apps/voice/svc_stream_runner.py
"""Streaming mode entry point runners.

These functions provide simple wrappers around StreamingVoiceService
for use by CLI and svc_core module selection logic.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from typing import Any

from .stream.svc_streaming import StreamingVoiceService


def _run_coro_in_thread(coro) -> Any:
    """Run coroutine in separate thread with its own event loop (no collision with @pytest.mark.asyncio)."""
    result_box: dict[str, Any] = {}
    error_box: dict[str, BaseException] = {}

    def _target():
        try:
            result_box["r"] = asyncio.run(coro)
        except BaseException as e:  # noqa: BLE001
            error_box["e"] = e

    t = threading.Thread(target=_target, name="svc-stream-runner", daemon=True)
    t.start()
    t.join()
    if "e" in error_box:
        raise error_box["e"]
    return result_box.get("r")


def run_once_stream(cfg: dict[str, Any], args) -> int:
    """Run streaming once mode (CLI/test entry point)."""
    service = StreamingVoiceService(cfg)
    try:
        # once() may be sync (calls asyncio.run internally) or async (test DummyService)
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
    """Start streaming in 'listen' mode (CLI/test entry point)."""
    service = StreamingVoiceService(cfg)
    try:
        # listen() may be sync or async – handle both
        ret = service.listen()
        if inspect.iscoroutine(ret):
            _run_coro_in_thread(ret)
        return 0
    finally:
        stop = getattr(service, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass


def run_ptt_stream(cfg: dict[str, Any], args) -> int:
    """PTT: enable hotword.enabled and delegate to run_listen_stream."""
    cfg2 = dict(cfg) if cfg else {}
    hot = dict(cfg2.get("hotword", {}))
    hot["enabled"] = True
    hot["engine"] = "ptt"
    cfg2["hotword"] = hot
    return run_listen_stream(cfg2, args)
