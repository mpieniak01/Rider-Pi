# apps/voice/svc_core.py
"""Voice service core - mode selection and minimal utilities."""

from __future__ import annotations

import os
from typing import Any

from .svc_file import run_listen_file, run_once_file


def _wants_stream(cfg: dict[str, Any], args) -> bool:
    """Check if streaming mode is requested."""
    # Primary check: explicit realtime transport in any component
    asr_cfg = cfg.get("asr", {})
    chat_cfg = cfg.get("chat", {})
    tts_cfg = cfg.get("tts", {})

    # Require explicit realtime transport
    realtime_requested = (
        asr_cfg.get("transport") == "realtime"
        or chat_cfg.get("transport") == "realtime"
        or tts_cfg.get("transport") == "realtime"
    )

    if not realtime_requested:
        return False

    # Check if API key is available for streaming mode
    stream_cfg = cfg.get("stream", {})
    auth = stream_cfg.get("auth", "env:OPENAI_API_KEY")

    if auth.startswith("env:"):
        env_key = auth[4:]
        api_key = os.environ.get(env_key, "")
        if not api_key:
            print(f"[voice.svc_core] WARNING: {env_key} not set, falling back to file mode")
            return False

    return True


def run_listen(cfg: dict[str, Any], args) -> int:
    """Main entry point for listen mode - delegates based on config."""
    if _wants_stream(cfg, args):
        print("[voice.svc_core] INFO: Using streaming mode (realtime WebSocket)")
        # Import here to avoid circular imports and optional dependencies
        try:
            from .svc_stream import run_listen_stream

            return run_listen_stream(cfg, args)
        except ImportError as e:
            print(f"[voice.svc_core] WARNING: Streaming mode requires additional dependencies: {e}")
            print("[voice.svc_core] INFO: Falling back to file mode...")
            return run_listen_file(cfg, args)
    else:
        print("[voice.svc_core] INFO: Using file mode (traditional pipeline)")
        return run_listen_file(cfg, args)


def run_once(cfg: dict[str, Any], args) -> int:
    """Main entry point for once mode - delegates based on config."""
    if _wants_stream(cfg, args):
        print("[voice.svc_core] INFO: Using streaming mode (realtime WebSocket)")
        # Import here to avoid circular imports and optional dependencies
        try:
            from .svc_stream import run_once_stream

            return run_once_stream(cfg, args)
        except ImportError as e:
            print(f"[voice.svc_core] WARNING: Streaming mode requires additional dependencies: {e}")
            print("[voice.svc_core] INFO: Falling back to file mode...")
            return run_once_file(cfg, args)
    else:
        print("[voice.svc_core] INFO: Using file mode (traditional pipeline)")
        return run_once_file(cfg, args)


# Mini utilities to avoid multiplying files
def mask_secret(s: str) -> str:
    """Mask a secret string for logging."""
    return "***" if s and len(s) > 3 else s


def clamp(v: float, lo: float, hi: float) -> float:
    """Clamp a value between bounds."""
    return max(lo, min(hi, v))
