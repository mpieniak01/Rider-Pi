# apps/voice/web.py
from __future__ import annotations

import audioop  # noqa: F401 - shared audio handler namespace
import base64
import io  # noqa: F401 - shared audio handler namespace
import math  # noqa: F401 - shared audio handler namespace
import os
import re
import shlex
import shutil
import struct  # noqa: F401 - shared audio handler namespace
import subprocess
import sys
import tempfile
import wave  # noqa: F401 - shared audio handler namespace
from typing import Any

from flask import Flask, Response, g, jsonify, request

from apps.voice import web_audio
from services.api_core.http_security import install as install_http_security

# ───────────────────────────────────────────────────────────────────────────────
# Instancja aplikacji + polyfill dla Flask < 2.0
# ───────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
install_http_security(app)

WEB_INIT_EVENT = "web.init"
WAV_MIMETYPE = "audio/wav"
TTS_CONTENT_DISPOSITION = "inline; filename=tts.wav"

if not hasattr(app, "get"):

    def _route_get(path, **kw):
        return app.route(path, methods=["GET"], **kw)

    def _route_post(path, **kw):
        return app.route(path, methods=["POST"], **kw)

    app.get = _route_get  # type: ignore[attr-defined]
    app.post = _route_post  # type: ignore[attr-defined]

# ───────────────────────────────────────────────────────────────────────────────
# Logger i konfiguracja
# ───────────────────────────────────────────────────────────────────────────────

try:
    from . import voice_logging

    logger = voice_logging.get_logger("voice.web")
except Exception:
    import logging

    logger = logging.getLogger("voice.web")


def _log_info(msg: str, **kwargs) -> None:
    """Safe logging helper that works with both custom and standard loggers."""
    if hasattr(logger, "event"):
        logger.event(msg, **kwargs)  # type: ignore[attr-defined]
    else:
        logger.info(f"{msg} {kwargs}" if kwargs else msg)


def _log_warning(msg: str, **kwargs) -> None:
    """Safe logging helper that works with both custom and standard loggers."""
    if hasattr(logger, "event"):
        logger.event(msg, **kwargs)  # type: ignore[attr-defined]
    else:
        logger.warning(f"{msg} {kwargs}" if kwargs else msg)


def _log_error(msg: str, **kwargs) -> None:
    """Safe logging helper that works with both custom and standard loggers."""
    if hasattr(logger, "event"):
        logger.event(msg, **kwargs)  # type: ignore[attr-defined]
    else:
        logger.error(f"{msg} {kwargs}" if kwargs else msg)


# ───────────────────────────────────────────────────────────────────────────────
# ENV loader (~/.bash_profile) — zapewnia dostęp do kluczy API (np. OPENAI_API_KEY)
# ───────────────────────────────────────────────────────────────────────────────
try:
    from .env_loader import ensure_env_from_bash_profile as _ensure_env_from_bash_profile  # type: ignore
except Exception:  # pragma: no cover
    _ensure_env_from_bash_profile = None  # type: ignore


def _maybe_load_env_from_bash_profile() -> None:
    if _ensure_env_from_bash_profile is None:
        _log_warning(WEB_INIT_EVENT, src="env_loader", detail="missing env_loader module")
        return
    try:
        _ensure_env_from_bash_profile()
        _log_info(WEB_INIT_EVENT, src="~/.bash_profile", status="env loaded")
    except Exception as exc:  # pragma: no cover
        _log_warning(WEB_INIT_EVENT, src="~/.bash_profile", error=str(exc))


if os.getenv("VOICE_WEB_LOAD_PROFILE", "1") == "1":
    _maybe_load_env_from_bash_profile()


def _dict_to_config_object(cfg_dict: dict) -> Any:
    """Convert nested dict to object with attribute access (cfg.chat.backend)."""
    return type(
        "Config",
        (),
        {k: type("Section", (), v) if isinstance(v, dict) else v for k, v in cfg_dict.items()},
    )()


@app.before_request
def _load_config():
    """Ładuje konfigurację do kontekstu Flask g przed każdym żądaniem."""
    if not hasattr(g, "config"):
        try:
            from . import config as voice_config

            # Ładujemy domyślną konfigurację voice.toml lub voice_local_file.toml
            cfg_dict = voice_config.load(os.getenv("VOICE_DOMAIN_CONFIG") or None)
            # Konwertujemy na obiekt z atrybutami dla wygody (cfg.chat.backend)
            g.config = _dict_to_config_object(cfg_dict)
        except Exception as e:
            _log_warning("web.config.load_failed", error=str(e))
            # Fallback: pusty obiekt konfiguracji
            g.config = type("Config", (), {})()


# ───────────────────────────────────────────────────────────────────────────────
# Opcjonalne lokalne backendy (Piper / Vosk) – importy „best-effort”
# ───────────────────────────────────────────────────────────────────────────────

_PIPER_OK = False
_VOSK_OK = False
PiperVoice = None
KaldiRecognizer = None
Model = None


def _load_piper_backend() -> bool:
    return web_audio._load_piper_backend(sys.modules[__name__])


def _load_vosk_backend() -> bool:
    return web_audio._load_vosk_backend(sys.modules[__name__])


# Ścieżki do modeli – można nadpisać ENV:
# Preferencje:
#   1) PIPER_MODEL (pełna ścieżka do .onnx)
#   2) PIPER_MODEL_DIR + PIPER_VOICE (np. dir + "pl_PL-mls-medium.onnx")
#   3) fallback: <PIPER_MODEL_DIR>/pl_PL-mls-medium.onnx
PIPER_MODEL = os.getenv("PIPER_MODEL", "").strip()
PIPER_MODEL_DIR = os.getenv("PIPER_MODEL_DIR", "/home/pi/robot/models/piper").rstrip("/")
PIPER_VOICE = os.getenv("PIPER_VOICE", "pl_PL-mls-medium.onnx").strip()

# Vosk
VOSK_MODEL = os.getenv("VOSK_MODEL", os.getenv("VOSK_MODEL_DIR", "/home/pi/robot/models/vosk/vosk-model-small-pl-0.22"))

# Cache instancji lokalnych backendów
_local_piper_voice = None
_local_vosk_model = None


def _resolve_piper_model_path(payload_voice: str | None = None) -> str:
    return web_audio._resolve_piper_model_path(sys.modules[__name__], payload_voice)


def _get_local_piper_voice(model_path: str | None = None):
    return web_audio._get_local_piper_voice(sys.modules[__name__], model_path)


def _get_local_vosk_model():
    return web_audio._get_local_vosk_model(sys.modules[__name__])


# ───────────────────────────────────────────────────────────────────────────────
# Pomocniki audio (minimalne; kompatybilne z Py3.9)
# ───────────────────────────────────────────────────────────────────────────────


def _is_wav(b: bytes) -> bool:
    return web_audio._is_wav(sys.modules[__name__], b)


def _read_wav_params(b: bytes):
    return web_audio._read_wav_params(sys.modules[__name__], b)


def _wrap_wav(pcm: bytes, sr: int, ch: int, sw: int = 2) -> bytes:
    return web_audio._wrap_wav(sys.modules[__name__], pcm, sr, ch, sw)


def _is_mp3(b: bytes) -> bool:
    return web_audio._is_mp3(sys.modules[__name__], b)


def _is_ogg(b: bytes) -> bool:
    return web_audio._is_ogg(sys.modules[__name__], b)


def _decode_with_tool_to_wav(audio: bytes) -> bytes | None:
    return web_audio._decode_with_tool_to_wav(sys.modules[__name__], audio)


# ── audio shaping: fade & tail ────────────────────────────────────────────────


def _apply_fade(pcm: bytes, sr: int, ch: int, sampwidth: int = 2, fade_in_ms: int = 15, fade_out_ms: int = 20) -> bytes:
    return web_audio._apply_fade(sys.modules[__name__], pcm, sr, ch, sampwidth, fade_in_ms, fade_out_ms)


def _append_tail(pcm: bytes, sr: int, ch: int, ms: int) -> bytes:
    return web_audio._append_tail(sys.modules[__name__], pcm, sr, ch, ms)


def _maybe_gain(pcm: bytes, gain: float) -> bytes:
    return web_audio._maybe_gain(sys.modules[__name__], pcm, gain)


# ── resampling ────────────────────────────────────────────────────────────────


def _resample_to(pcm: bytes, in_sr: int, in_ch: int, target_sr: int, target_ch: int) -> bytes:
    return web_audio._resample_to(sys.modules[__name__], pcm, in_sr, in_ch, target_sr, target_ch)


def _ensure_wav_bytes(audio: bytes, sample_rate: int | None, fmt: str | None) -> bytes | None:
    return web_audio._ensure_wav_bytes(sys.modules[__name__], audio, sample_rate, fmt)


# ───────────────────────────────────────────────────────────────────────────────
# Piper: ujednolicony helper generujący WAV niezależnie od wariantu API
# ───────────────────────────────────────────────────────────────────────────────


def _piper_synthesize_wav_bytes(voice, text: str, model_path: str | None = None) -> tuple[bytes, int | None]:
    return web_audio._piper_synthesize_wav_bytes(sys.modules[__name__], voice, text, model_path)


# ───────────────────────────────────────────────────────────────────────────────
# Trasy
# ───────────────────────────────────────────────────────────────────────────────


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.get("/api/tts-test")
def api_tts_test():
    """Pół sekundy tonu 1 kHz jako pewny WAV — do diagnostyki."""
    sr = int(os.environ.get("VOICE_RATE", "48000"))
    ch = int(os.environ.get("VOICE_CHANNELS", "2"))
    dur = 0.5
    n = int(sr * dur)
    pcm = bytearray()
    for i in range(n):
        s = int(0.20 * 32767 * math.sin(2 * math.pi * 1000 * (i / sr)))
        if ch == 1:
            pcm += struct.pack("<h", s)
        else:
            pcm += struct.pack("<hh", s, s)
    pcm = _apply_fade(
        bytes(pcm),
        sr,
        ch,
        2,
        int(os.environ.get("VOICE_FADE_IN_MS", "15")),
        int(os.environ.get("VOICE_FADE_OUT_MS", "20")),
    )
    pcm = _append_tail(pcm, sr, ch, int(os.environ.get("VOICE_TAIL_MS", "300")))
    pcm = _maybe_gain(pcm, float(os.environ.get("VOICE_GAIN", "1.0")))
    wav = _wrap_wav(pcm, sr, ch, 2)
    return Response(
        wav,
        mimetype=WAV_MIMETYPE,
        headers={"Content-Disposition": "inline; filename=test.wav"},
    )


@app.post("/api/tts")
def api_tts():
    """
    JSON in: { "text": "...", "backend|provider": "openai|gemini|local|piper", "format": "wav|mp3", "voice": "..." }
    Domyślnie zwraca **audio/wav** (surowe bajty).
    Dodaj ?b64=1 aby dostać JSON: { audio_b64: "..." }.
    """
    try:
        payload = request.get_json(force=True, silent=True) or {}
        text = (payload.get("text") or "").strip()
        if not text:
            return jsonify({"status": "error", "error": "missing text"}), 400

        configured = getattr(getattr(getattr(g, "config", None), "tts", None), "backend", "")
        backend = (
            (payload.get("backend") or payload.get("provider") or payload.get("tts") or configured).strip().lower()
        )

        # 1) Kanał lokalny (Piper)
        if backend in ("local", "piper"):
            if not _load_piper_backend():
                return jsonify({"status": "error", "error": "piper module not available"}), 500
            try:
                voice_name = payload.get("voice")
                model_path = _resolve_piper_model_path(voice_name if isinstance(voice_name, str) else None)
                voice = _get_local_piper_voice(model_path)

                wav_bytes, sr = _piper_synthesize_wav_bytes(voice, text, model_path)
                wav = _ensure_wav_bytes(wav_bytes, sr, "wav")
            except Exception as e:
                return jsonify({"status": "error", "error": f"local piper failed: {e}"}), 500

            if not wav or not _is_wav(wav):
                return jsonify({"status": "error", "error": "piper produced no WAV"}), 500

            if request.args.get("b64") == "1":
                b64 = base64.b64encode(wav).decode("ascii")
                return jsonify({"status": "ok", "fmt": "wav", "audio_b64": b64})
            return Response(
                wav,
                mimetype=WAV_MIMETYPE,
                headers={"Content-Disposition": TTS_CONTENT_DISPOSITION},
            )

        # 2) Pozostałe kanały – OpenAI/Gemini
        from . import config as voice_config
        from .tts import TTSConfig, synthesize

        overrides = {}
        tts_pairs = []
        for k in ("backend", "provider", "format", "voice", "model"):
            if k in payload:
                key = "backend" if k in ("backend", "provider") else k
                tts_pairs.append(f"{key}={payload[k]}")
        if tts_pairs:
            overrides = {"tts": voice_config.override_from_pairs("tts", tts_pairs)["tts"]}

        cfg = voice_config.load(None, overrides=overrides)

        cfg_backend = str(cfg.get("tts", {}).get("backend", "")).lower()
        if cfg_backend in ("local", "piper"):
            if not _load_piper_backend():
                return jsonify({"status": "error", "error": "piper module not available"}), 500
            try:
                model_path = _resolve_piper_model_path()
                voice = _get_local_piper_voice(model_path)
                wav_bytes, sr = _piper_synthesize_wav_bytes(voice, text, model_path)
                wav = _ensure_wav_bytes(wav_bytes, sr, "wav")
            except Exception as e:
                return jsonify({"status": "error", "error": f"local piper failed: {e}"}), 500

            if not wav or not _is_wav(wav):
                return jsonify({"status": "error", "error": "piper produced no WAV"}), 500

            if request.args.get("b64") == "1":
                b64 = base64.b64encode(wav).decode("ascii")
                return jsonify({"status": "ok", "fmt": "wav", "audio_b64": b64})
            return Response(
                wav,
                mimetype=WAV_MIMETYPE,
                headers={"Content-Disposition": TTS_CONTENT_DISPOSITION},
            )

        # W przeciwnym razie – chmurowy synth
        audio, sr, _channels, fmt = synthesize(text, TTSConfig(**cfg["tts"]))
        wav = _ensure_wav_bytes(audio, sr, fmt)
        if not wav or not _is_wav(wav):
            return jsonify({"status": "error", "error": "synthesis produced no WAV"}), 500

        if request.args.get("b64") == "1":
            b64 = base64.b64encode(wav).decode("ascii")
            return jsonify({"status": "ok", "fmt": "wav", "audio_b64": b64})

        return Response(
            wav,
            mimetype=WAV_MIMETYPE,
            headers={"Content-Disposition": TTS_CONTENT_DISPOSITION},
        )

    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ───────────────────────────────────────────────────────────────────────────────
# Lokalny ASR (Vosk) – przyjmuje WAV (lub MP3/OGG), zwraca JSON
# ───────────────────────────────────────────────────────────────────────────────


@app.post('/api/asr')
def api_asr():
    return web_audio.api_asr(sys.modules[__name__])


# ───────────────────────────────────────────────────────────────────────────────
# Lokalny Chat (llama.cpp) – przyjmuje JSON, zwraca JSON
# ───────────────────────────────────────────────────────────────────────────────


def _build_llama_prompt(cfg: Any, messages: list[dict[str, str]]) -> str:
    """Tworzy prompt dla llama.cpp z pełnej historii wiadomości w formacie ChatML."""
    system_prompt = cfg.system_prompt or "Jesteś pomocnym asystentem."
    prompt_parts = [f"<|system|>\n{system_prompt}<|end|>"]

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "user":
            prompt_parts.append(f"<|user|>\n{content}<|end|>")
        elif role == "assistant":
            prompt_parts.append(f"<|assistant|>\n{content}<|end|>")

    # Dodajemy tag asystenta na końcu, aby model wiedział, że ma odpowiedzieć
    prompt_parts.append("<|assistant|>")

    return "\n".join(prompt_parts)


@app.route("/api/chat", methods=["POST"])
def api_chat_local():
    """
    Handler dla lokalnego LLM (llama.cpp).
    Wywołuje binarkę systemową przez subprocess.
    """
    try:
        chat_cfg = g.config.chat
        if not chat_cfg or chat_cfg.backend != "local":
            return jsonify({"ok": False, "error": "Lokalny backend czatu nie jest skonfigurowany."}), 500

        # Pobierz timeout wcześnie, aby był dostępny w exception handlerach
        timeout_sec = getattr(chat_cfg, "timeout", 20.0)

        # Sprawdzenie, czy binarka i model istnieją
        llm_main_path = os.getenv("VOICE_LLM_MAIN_PATH", getattr(chat_cfg, "llm_main_path", "llama.cpp/main"))
        llm_model_path = os.getenv(
            "VOICE_LLM_MODEL_PATH",
            getattr(chat_cfg, "llm_model_path", "models/llm/phi-3-mini-3.8b-instruct.Q4_K_M.gguf"),
        )
        llm_extra_args = getattr(
            chat_cfg,
            "llm_extra_args",
            "-t 4 -n 256 --ctx-size 1024 --simple-io --temp 0.7",
        )

        # Walidacja bezpieczeństwa: używamy podejścia whitelist - tylko dozwolone znaki w ścieżkach
        # Dozwolone: a-z, A-Z, 0-9, /, _, ., -
        if not re.match(r"^[a-zA-Z0-9/_.-]+$", llm_main_path) or not re.match(r"^[a-zA-Z0-9/_.-]+$", llm_model_path):
            _log_error("web.chat.local.invalid_path", path="contains invalid characters")
            return jsonify({"ok": False, "error": "Nieprawidłowa ścieżka w konfiguracji."}), 500

        llm_main_path = shutil.which(llm_main_path) or llm_main_path

        if not os.path.exists(llm_main_path):
            return jsonify({"ok": False, "error": "Nie znaleziono binarki llama.cpp"}), 500
        if not os.path.exists(llm_model_path):
            return jsonify({"ok": False, "error": "Nie znaleziono modelu LLM"}), 500

        payload = request.get_json(force=True, silent=True) or {}
        messages = payload.get("messages") or []
        if not messages:
            return jsonify({"ok": False, "error": "Brak wiadomości (messages) w payload."}), 400

        prompt = _build_llama_prompt(chat_cfg, messages)

        # Ograniczenie długości promptu dla bezpieczeństwa
        MAX_PROMPT_LEN = 8192
        if len(prompt) > MAX_PROMPT_LEN:
            return jsonify({"ok": False, "error": f"Prompt za długi (max {MAX_PROMPT_LEN} znaków)"}), 400

        extra_args = shlex.split(llm_extra_args or "")

        # Budowanie komendy - używamy listy argumentów, co jest bezpieczniejsze niż shell=True
        # BEZPIECZEŃSTWO: Dane użytkownika (messages) trafiają do 'prompt', który jest przekazywany
        # jako wartość flagi '-p'. Ponieważ używamy subprocess.run() z listą (nie shell=True),
        # jako dane wejściowe przez plik tymczasowy (nie jako argument linii poleceń), co minimalizuje
        # ryzyko argument injection oraz potencjalnych błędów w parsowaniu argumentów przez llama.cpp.
        # Dodatkowo ograniczamy długość promptu.
        MAX_PROMPT_LEN = 4096
        if len(prompt) > MAX_PROMPT_LEN:
            return jsonify({"ok": False, "error": f"Prompt za długi (max {MAX_PROMPT_LEN} znaków)"}), 400

        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as prompt_file:
            prompt_file.write(prompt)
            prompt_file.flush()
            prompt_file_path = prompt_file.name

        # Zakładamy, że llama.cpp obsługuje flagę -f <plik> do wczytania promptu z pliku
        cmd = [
            llm_main_path,
            "-m",
            llm_model_path,
            "-f",
            prompt_file_path,
        ] + extra_args

        _log_info("web.chat.local.exec", cmd_len=len(cmd))

        # Wywołanie subprocessu - używamy listy args (nie shell=True) dla bezpieczeństwa
        # To jest bezpieczne przed command injection oraz argument injection, bo prompt nie jest już argumentem
        timeout_sec = getattr(chat_cfg, "timeout", 20.0)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_sec,
            )
        finally:
            try:
                os.remove(prompt_file_path)
            except Exception:
                pass

        if proc.returncode != 0:
            _log_error("web.chat.local.fail", code=proc.returncode, stderr_len=len(proc.stderr))
            # Nie ujawniamy szczegółów stderr użytkownikowi ze względów bezpieczeństwa
            return jsonify({"ok": False, "error": "Błąd wykonania llama.cpp"}), 500

        # Odpowiedź jest na stdout (dzięki --simple-io)
        # Usuwamy prompt, który llama.cpp czasem powtarza na początku
        full_output = proc.stdout.strip()
        text_response = full_output.removeprefix(prompt).strip()

        _log_info("web.chat.local.ok", chars=len(text_response))

        # Zwracamy format zgodny z oczekiwaniami ChatSession._ask_local_http
        return jsonify(
            {
                "ok": True,
                "text": text_response,
                "message": {"role": "assistant", "content": text_response},
            }
        )

    except subprocess.TimeoutExpired:
        _log_warning("web.chat.local.timeout", timeout=timeout_sec)
        return jsonify(
            {"ok": False, "error": "Przekroczono limit czasu oczekiwania na llama.cpp"}
        ), 504  # Gateway Timeout  # noqa: E501
    except Exception as e:
        # Nie ujawniamy szczegółów wyjątku użytkownikowi ze względów bezpieczeństwa
        _log_error("web.chat.local.error", error_type=type(e).__name__)
        return jsonify({"ok": False, "error": "Wewnętrzny błąd serwera"}), 500


# ───────────────────────────────────────────────────────────────────────────────
# Uruchamianie modułem: python -m apps.voice.web
# ───────────────────────────────────────────────────────────────────────────────


def main():
    # Load bind address from config
    try:
        from . import config as voice_config

        cfg_dict = voice_config.load("voice_web.toml")
        bind_addr = cfg_dict.get("server", {}).get("bind", "127.0.0.1:8092")
    except ImportError:
        # Fallback to default
        bind_addr = "127.0.0.1:8092"

    # Parse host:port
    try:
        host, port = bind_addr.split(":")
        port = int(port)
    except (ValueError, IndexError):
        _log_error("web.main.invalid_bind", bind=bind_addr)
        host, port = "127.0.0.1", 8092

    _log_info("web.main.starting", host=host, port=port)
    app.run(host=host, port=port)


if __name__ == "__main__":
    main()
