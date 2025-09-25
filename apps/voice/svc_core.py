# apps/voice/svc_core.py
"""Voice service core - mode selection and minimal utilities."""

from __future__ import annotations

from typing import Any

from .svc_file import run_listen_file, run_once_file


def _wants_stream(cfg: dict[str, Any], args) -> bool:
    """Check if streaming mode is requested."""
    # Primary check: explicit realtime transport in any component
    asr_cfg = cfg.get("asr", {})
    chat_cfg = cfg.get("chat", {}) 
    tts_cfg = cfg.get("tts", {})
    
    # Require explicit realtime transport
    if (asr_cfg.get("transport") == "realtime" or
        chat_cfg.get("transport") == "realtime" or  
        tts_cfg.get("transport") == "realtime"):
        return True
        
    return False


def run_listen(cfg: dict[str, Any], args) -> int:
    """Main entry point for listen mode - delegates based on config."""
    if _wants_stream(cfg, args):
        # Import here to avoid circular imports and optional dependencies
        try:
            from .svc_stream import run_listen_stream
            return run_listen_stream(cfg, args)
        except ImportError as e:
            print(f"Streaming mode requires additional dependencies: {e}")
            print("Falling back to file mode...")
            return run_listen_file(cfg, args)
    else:
        return run_listen_file(cfg, args)


def run_once(cfg: dict[str, Any], args) -> int:
    """Main entry point for once mode - delegates based on config."""
    if _wants_stream(cfg, args):
        # Import here to avoid circular imports and optional dependencies
        try:
            from .svc_stream import run_once_stream
            return run_once_stream(cfg, args)
        except ImportError as e:
            print(f"Streaming mode requires additional dependencies: {e}")
            print("Falling back to file mode...")
            return run_once_file(cfg, args)
    else:
        return run_once_file(cfg, args)


# Mini utilities to avoid multiplying files
def mask_secret(s: str) -> str:
    """Mask a secret string for logging."""
    return "***" if s and len(s) > 3 else s


def clamp(v: float, lo: float, hi: float) -> float:
    """Clamp a value between bounds."""
    return max(lo, min(hi, v))
