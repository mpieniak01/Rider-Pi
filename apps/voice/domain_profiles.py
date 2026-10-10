"""Selected voice domains and passive backend availability; no audio/model I/O."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
from pathlib import Path

DOMAINS = {"asr": {"asr"}, "tts": {"tts"}, "text": {"chat"}, "voice": {"asr", "tts", "chat"}}


def worker_bind() -> tuple[str, int]:
    from apps.voice import config

    path = Path(os.getenv("VOICE_WEB_CONFIG", "config/voice_web.toml"))
    cfg = config.load(path.resolve()) if path.is_file() else {}
    bind = os.getenv("VOICE_WEB_BIND", cfg.get("server", {}).get("bind", "127.0.0.1:8092"))
    host, port = bind.rsplit(":", 1)
    return host.strip("[]"), int(port)


def expand(domain: str) -> set[str]:
    if domain not in DOMAINS:
        raise ValueError("domain must be voice, text, asr or tts")
    return set(DOMAINS[domain])


def requested_domains(path: Path | None = None) -> set[str]:
    path = path or Path(os.getenv("FEATURE_STATE_PATH", "/run/rider-motion/feature_state.json"))
    try:
        if path.stat().st_size > 512000:
            return set()
        state = json.loads(path.read_text(encoding="utf-8"))
        domains = set()
        for task in state.get("features", []):
            if (
                task.get("name") not in {"s5_voice", "s10_ai_providers"}
                or task.get("requested") is not True
                or task.get("state") not in {"starting", "ready", "partial"}
                or "rider-voice-web.service" not in task.get("members", [])
            ):
                continue
            domain = task.get("options", {}).get("domain", "voice" if task["name"] == "s5_voice" else "text")
            if domain in DOMAINS:
                domains.update(expand(domain))
        admin = state.get("service_domains", {}).get("rider-voice-web.service")
        if admin in DOMAINS:
            domains.update(expand(admin))
        return domains
    except (OSError, ValueError, TypeError, AttributeError):
        return set()


def availability(domains: set[str], *, find_spec=importlib.util.find_spec) -> dict:
    missing = []
    required = []
    if "asr" in domains:
        required.append("vosk")
        model = Path(
            os.getenv("VOSK_MODEL", os.getenv("VOSK_MODEL_DIR", "/home/pi/robot/models/vosk/vosk-model-small-pl-0.22"))
        )
        if not model.is_dir():
            missing.append("asr_model_unavailable")
    if "tts" in domains:
        required.append("piper")
        model = Path(
            os.getenv(
                "PIPER_MODEL",
                str(
                    Path(os.getenv("PIPER_MODEL_DIR", "/home/pi/robot/models/piper"))
                    / os.getenv("PIPER_VOICE", "pl_PL-mls-medium.onnx")
                ),
            )
        )
        if not model.is_file() or not Path(str(model) + ".json").is_file():
            missing.append("tts_model_unavailable")
    for module in required:
        try:
            present = find_spec(module) is not None
        except (ImportError, ValueError):
            present = False
        if not present:
            missing.append(module)
    if "chat" in domains:
        provider = os.getenv("VOICE_WEB_LLM_PROVIDER", "local")
        if provider != "local":
            missing.append("chat_backend_disabled")
        else:
            try:
                from apps.voice import config

                chat = config.load(os.getenv("VOICE_DOMAIN_CONFIG") or None).get("chat", {})
            except (ImportError, OSError, ValueError):
                chat = {}
            command = os.getenv("VOICE_LLM_MAIN_PATH", chat.get("llm_main_path", "llama.cpp/main"))
            model = Path(
                os.getenv(
                    "VOICE_LLM_MODEL_PATH",
                    chat.get("llm_model_path", "models/llm/phi-3-mini-3.8b-instruct.Q4_K_M.gguf"),
                )
            )
            if (
                chat.get("backend") != "local"
                or not re.fullmatch(r"[a-zA-Z0-9/_.-]+", command)
                or not os.access(shutil.which(command) or command, os.X_OK)
                or not model.is_file()
            ):
                missing.append("chat_backend_unavailable")
    capabilities = {
        domain: {
            "ready": not any(
                failure.startswith(domain + "_") or failure == {"asr": "vosk", "tts": "piper"}.get(domain)
                for failure in missing
            )
        }
        for domain in domains
    }
    return {
        "ready": bool(domains) and not missing,
        "domains": sorted(domains),
        "missing": missing,
        "capabilities": capabilities,
        "source": "selected_voice_profile",
    }
