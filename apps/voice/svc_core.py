# apps/voice/svc_core.py
"""Voice service core - mode selection and minimal utilities."""

from __future__ import annotations

import os

os.environ.setdefault(
    "OPENAI_REALTIME_ENDPOINT", os.environ.get("OPENAI_REALTIME_ENDPOINT", "wss://example.invalid")
)  # CI default dummy endpoint
import re
from typing import Any

# Importy "file mode" — zawsze dostępne
from .svc_file import run_listen_file, run_once_file


def _wants_stream(cfg: dict[str, Any], args) -> bool:
    """
    Zwraca True, jeśli użytkownik realnie żąda trybu streamingowego
    *i* mamy minimalnie wymaganą konfigurację (klucz + endpoint).
    """
    asr_cfg = cfg.get("asr", {}) or {}
    chat_cfg = cfg.get("chat", {}) or {}
    tts_cfg = cfg.get("tts", {}) or {}

    realtime_requested = (
        str(asr_cfg.get("transport", "")).lower() == "realtime"
        or str(chat_cfg.get("transport", "")).lower() == "realtime"
        or str(tts_cfg.get("transport", "")).lower() == "realtime"
    )
    if not realtime_requested:
        return False

    # auth
    stream_cfg = cfg.get("stream", {}) or {}
    auth = str(stream_cfg.get("auth", "env:OPENAI_API_KEY"))
    if auth.startswith("env:"):
        env_key = auth[4:]
        api_key = (os.environ.get(env_key) or "").strip()
        if not api_key:
            print(f"[voice.svc_core] WARNING: {env_key} not set, falling back to file mode")
            return False
    elif not auth.strip():
        print("[voice.svc_core] WARNING: empty stream.auth, falling back to file mode")
        return False

    # endpoint (z configu lub ENV)
    endpoint = (stream_cfg.get("endpoint") or os.environ.get("OPENAI_REALTIME_ENDPOINT") or "").strip()
    if not endpoint:
        print(
            "[voice.svc_core] WARNING: realtime endpoint missing (stream.endpoint or OPENAI_REALTIME_ENDPOINT). "
            "Falling back to file mode"
        )
        return False

    return True


def _mode_from_cfg(cfg: dict[str, Any]) -> str:
    """
    Ujednolicony detektor trybu:
    - 'realtime' jeśli którakolwiek z sekcji asr/chat/tts ma transport='realtime'
      i jest dostępny klucz (env) oraz endpoint dla streamingu,
    - w przeciwnym razie 'file'.
    """
    dummy_args = object()
    return "realtime" if _wants_stream(cfg, dummy_args) else "file"


def run_listen(cfg: dict[str, Any], args) -> int:
    if _wants_stream(cfg, args):
        print("[voice.svc_core] INFO: Using streaming mode (realtime WebSocket)")
        try:
            from .svc_stream_runner import run_listen_stream

            return run_listen_stream(cfg, args)
        except ImportError as e:
            print(f"[voice.svc_core] WARNING: Streaming mode requires additional dependencies: {e}")
            print("[voice.svc_core] INFO: Falling back to file mode…")
            return run_listen_file(cfg, args)
    else:
        print("[voice.svc_core] INFO: Using file mode (traditional pipeline)")
        return run_listen_file(cfg, args)


def run_once(cfg: dict[str, Any], args) -> int:
    if _wants_stream(cfg, args):
        print("[voice.svc_core] INFO: Using streaming mode (realtime WebSocket)")
        try:
            from .svc_stream_runner import run_once_stream

            return run_once_stream(cfg, args)
        except ImportError as e:
            print(f"[voice.svc_core] WARNING: Streaming mode requires additional dependencies: {e}")
            print("[voice.svc_core] INFO: Falling back to file mode…")
            return run_once_file(cfg, args)
    else:
        print("[voice.svc_core] INFO: Using file mode (traditional pipeline)")
        return run_once_file(cfg, args)


# ──────────────────────────────────────────────────────────────────────────────
# Mini utilities (masking, math)
# ──────────────────────────────────────────────────────────────────────────────


def mask_secret(s: str, keep_tail: int = 4) -> str:
    """
    Zamaskuj sekret do logów.
    - Dla prostych tokenów: zostawia ostatnie `keep_tail` znaków, resztę zamazuje.
    - Dla URL-i: dodatkowo maskuje wartości znanych parametrów (np. model=…).
    """
    if not s:
        return s

    # Prosta redakcja parametrów URL (model=, key=)
    try:

        def _redact(match: re.Match[str]) -> str:
            k = match.group(1)
            return f"{k}=***"

        s = re.sub(r"(model|key|api_key)=([^&]+)", _redact, s, flags=re.IGNORECASE)
    except Exception:
        pass

    if len(s) <= max(1, keep_tail):
        return "***"

    head = len(s) - keep_tail
    return ("*" * max(3, head)) + s[-keep_tail:]


def clamp(v: float, lo: float, hi: float) -> float:
    """Clamp a value between bounds."""
    return max(lo, min(hi, v))
