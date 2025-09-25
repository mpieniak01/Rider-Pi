# apps/voice/svc_core.py
"""Voice service core - mode selection and minimal utilities."""

from __future__ import annotations

from typing import Any

from .svc_file import run_listen_file, run_once_file


def _wants_stream(cfg: dict[str, Any], args) -> bool:
    """Check if streaming mode is requested (always False in this refactor)."""
    return False  # No streaming in this PR


def run_listen(cfg: dict[str, Any], args) -> int:
    """Main entry point for listen mode - delegates to file mode."""
    return run_listen_file(cfg, args)


def run_once(cfg: dict[str, Any], args) -> int:
    """Main entry point for once mode - delegates to file mode."""
    return run_once_file(cfg, args)


# Mini utilities to avoid multiplying files
def mask_secret(s: str) -> str:
    """Mask a secret string for logging."""
    return "***" if s and len(s) > 3 else s


def clamp(v: float, lo: float, hi: float) -> float:
    """Clamp a value between bounds."""
    return max(lo, min(hi, v))
