# apps/voice/svc_core.py
"""Voice service core - mode selection and minimal utilities."""

from __future__ import annotations

import os
import time

os.environ.setdefault(
    "OPENAI_REALTIME_ENDPOINT",
    os.environ.get("OPENAI_REALTIME_ENDPOINT", "wss://example.invalid"),
)  # CI default dummy endpoint
import re
import threading
from typing import Any

# AI mode adapter for checking processing mode
from .ai_mode_adapter import log_voice_mode_status, should_offload_to_pc
from .audio.capture import AudioCapture, CaptureConfig
from .audio.playback import play_bytes
from .offload_bridge import VoiceOffloadBridge

# Importy "file mode" — zawsze dostępne
from .svc_file import VoiceService, run_listen_file, run_once_file
from .svc_signals import setup_signals

try:
    from services import provider_registry
except ImportError:
    provider_registry = None  # type: ignore


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


def _monitor_ai_mode_changes(service_instance, stop_event: threading.Event) -> None:
    """Monitor AI mode changes and stop service if mode switches to pc_offload.

    Args:
        service_instance: VoiceService instance with stop_event
        stop_event: Event to signal monitoring thread to stop
    """
    try:
        from common.bus import TOPIC_PROVIDER_VOICE_STATE, TOPIC_SYSTEM_AI_MODE_CHANGED, BusSub

        sub = BusSub([TOPIC_SYSTEM_AI_MODE_CHANGED, TOPIC_PROVIDER_VOICE_STATE])
        print("[voice.svc_core] AI mode monitor started", flush=True)

        while not stop_event.is_set():
            try:
                topic, payload = sub.recv(timeout_ms=500)
                if not (topic and payload):
                    continue
                if topic == TOPIC_SYSTEM_AI_MODE_CHANGED:
                    new_mode = payload.get("mode", "")
                    print(f"[voice.svc_core] AI mode change detected: {new_mode}", flush=True)
                    trigger_stop = new_mode == "pc_offload"
                elif topic == TOPIC_PROVIDER_VOICE_STATE:
                    new_mode = payload.get("mode", "")
                    print(f"[voice.svc_core] Provider voice state: {new_mode}", flush=True)
                    trigger_stop = new_mode == "pc"
                else:
                    continue
                if trigger_stop:
                    print(
                        "[voice.svc_core] Switching to PC provider - stopping local voice service",
                        flush=True,
                    )
                    if hasattr(service_instance, "stop_event"):
                        service_instance.stop_event.set()
                    stop_event.set()
                    break
            except Exception as e:
                print(f"[voice.svc_core] WARNING: Exception in AI mode monitor loop: {e}", flush=True)

        sub.close()
    except Exception as e:
        print(f"[voice.svc_core] WARNING: AI mode monitor error: {e}", flush=True)


def _trigger_voice_fallback(reason: str) -> None:
    print(f"[voice.svc_core] FALLBACK to local voice due to: {reason}", flush=True)
    if provider_registry:
        try:
            provider_registry.update_domain_status("voice", "fallback", reason=reason)
            provider_registry.set_domain_mode("voice", "local", reason=reason)
        except Exception as exc:  # noqa: BLE001
            print(f"[voice.svc_core] WARNING: provider registry fallback failed: {exc}", flush=True)


def _run_pc_offload(cfg: dict[str, Any], args) -> int:
    print("[voice.svc_core] Provider mode = PC. Starting offload bridge…", flush=True)
    cap_cfg = CaptureConfig(**dict(cfg.get("capture") or {}))
    bridge = VoiceOffloadBridge()
    service = VoiceService(cfg)
    setup_signals(service)
    timeout_s = float(os.getenv("VOICE_OFFLOAD_RESULT_TIMEOUT", "5.0"))
    last_result_ts = time.time()
    try:
        bridge.start()
        print(
            f"[voice.svc_core] Streaming audio chunks (rate={cap_cfg.sample_rate} Hz) to PC topic voice.asr.request",
            flush=True,
        )
        with AudioCapture(cap_cfg) as cap:
            for frame in cap.frames():
                if not should_offload_to_pc():
                    print("[voice.svc_core] Provider switched to local - stopping offload", flush=True)
                    return 0
                bridge.publish_audio_chunk(frame, cap_cfg.sample_rate)
                for result in bridge.iter_results():
                    text = (result.get("text") or result.get("transcript") or "").strip()
                    if not text:
                        continue
                    print(f"[voice.offload] ASR result: {text}", flush=True)
                    language = result.get("language") or "unknown"
                    speak_reply = bool(result.get("speak", True))
                    last_result_ts = time.time()
                    try:
                        service.handle_external_transcript(
                            text,
                            language=language,
                            raw=result,
                            speak=speak_reply,
                        )
                    except Exception as exc:
                        print(f"[voice.svc_core] ERROR processing PC transcript: {exc}", flush=True)
                for chunk in bridge.iter_tts_chunks():
                    try:
                        audio_bytes, audio_format, sample_rate = service._decode_tts_override(chunk)  # noqa: SLF001
                        if audio_bytes:
                            play_bytes(
                                audio_bytes,
                                audio_format or "wav",
                                service._play_cfg,
                                service.logger,
                                sample_rate=sample_rate,
                            )
                    except Exception as exc:
                        print(f"[voice.svc_core] ERROR playing TTS chunk: {exc}", flush=True)
                if timeout_s > 0 and (time.time() - last_result_ts) > timeout_s:
                    _trigger_voice_fallback("pc_timeout")
                    return 1
    except KeyboardInterrupt:
        print("[voice.svc_core] Offload interrupted by user", flush=True)
    except Exception as exc:
        print(f"[voice.svc_core] ERROR during PC offload: {exc}", flush=True)
        _trigger_voice_fallback("pc_error")
        return 2
    finally:
        service.stop()
        bridge.stop()
    return 0


def run_listen(cfg: dict[str, Any], args) -> int:
    # Log AI mode status at startup
    log_voice_mode_status()

    # Check if we should offload to PC
    if should_offload_to_pc():
        return _run_pc_offload(cfg, args)

    # Local mode - proceed with normal operation
    print("[voice.svc_core] AI Mode: local - using local ASR/TTS/NLU engines", flush=True)

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
