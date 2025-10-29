# Technology Usage Analysis Report

## Executive Summary

This report provides a comprehensive analysis of technology usage in the Rider-Pi project, identifying all key technologies, dependencies, and their usage locations across the codebase.

### Analysis Scope

- **Files Analyzed**: 314
- **Subdirectories Scanned**: apps, services, common, drivers, scripts, tests, sim, config, examples, tools, web, systemd
- **Analysis Date**: 2025-10-29
- **Root Directory**: Excluded (as per requirements)

### Key Findings

The analysis identified **12 major technology categories** across the codebase:

| Technology Category | Files Found | Key Technologies |
|---------------------|-------------|------------------|
| **LLM Technologies** | 49 | OpenAI GPT, Google Gemini, Anthropic Claude |
| **ASR (Speech Recognition)** | 31 | Vosk, OpenAI Whisper, Google Speech |
| **TTS (Text-to-Speech)** | 50 | Piper TTS, OpenAI TTS, Google TTS |
| **NLU (Language Understanding)** | 20 | Custom NLU, Dialogflow integration |
| **Vision Technologies** | 37 | TensorFlow Lite, OpenCV, object detection |
| **Camera Integration** | 120 | Picamera2, V4L2, OpenCV capture |
| **Audio Hardware** | 69 | ALSA, PyAudioALSA, audio capture/playback |
| **Robot Control** | 102 | XGO robot library, motion control |
| **Display Hardware** | 83 | LCD (ILI9xxx), PIL/Pillow, SPI |
| **GPIO and Sensors** | 46 | RPi.GPIO, SPI, I2C sensors |
| **MQTT and Messaging** | 62 | Paho MQTT, ZeroMQ bus |
| **State Management** | 88 | FSM, state transitions, telemetry |

### Major Integration Points

1. **Voice Pipeline**: ASR → Chat (LLM) → TTS with multiple backend support (OpenAI, Google Gemini, local Vosk/Piper)
2. **Vision Pipeline**: Camera → Detection (TFLite/HOG) → LCD display + bus publishing
3. **Robot Control**: MQTT/ZeroMQ bus → Motion module → XGO hardware driver
4. **Multi-modal Interface**: Audio (microphone/speaker), Vision (camera), Display (LCD), Control (buttons)

### External Dependencies

**68 references** to `/home/pi/robot/` path found across scripts and configuration files, indicating deployment-specific paths that reference code outside the project directory structure.

## Table of Contents

1. [LLM Technologies](#llm-technologies)
2. [ASR (Automatic Speech Recognition)](#asr-automatic-speech-recognition)
3. [TTS (Text-to-Speech)](#tts-text-to-speech)
4. [NLU (Natural Language Understanding)](#nlu-natural-language-understanding)
5. [Vision Technologies](#vision-technologies)
6. [Camera Integration](#camera-integration)
7. [Audio Hardware](#audio-hardware)
8. [Robot Control](#robot-control)
9. [Display Hardware](#display-hardware)
10. [GPIO and Sensors](#gpio-and-sensors)
11. [MQTT and Messaging](#mqtt-and-messaging)
12. [State Management](#state-management)
13. [External References](#external-references)

---

## LLM Technologies

**Files with LLM Technologies references**: 49

### apps/

#### `apps/chat/main.py`

*13 references found. Showing first 5:*

- Line 5: `apps/chat/main.py — Chat: audio.transcript -> (OpenAI) -> tts.speak`
- Line 56: `# --- OpenAI client ---`
- Line 58: `from openai import OpenAI`
- Line 60: `log(f"BLAD: brak pakietu openai: {e}")`
- Line 73: `client = OpenAI(api_key=OPENAI_API_KEY)`

#### `apps/ui/manager.py`

- Line 235: `log(f"start: mode={DIM_MODE} dim={DIM_SEC}s off={OFF_SEC}s chat={CHAT_MODE}")`

#### `apps/voice/asr.py`

*20 references found. Showing first 5:*

- Line 23: `backend: str = "openai"  # "openai" | "google" | "vosk" | "local"`
- Line 24: `model: str | None = None  # nazwa/model backendu (np. dla OpenAI / Gemini)`
- Line 99: `if backend == "openai":`
- Line 151: `from openai import OpenAI`
- Line 153: `raise ASRError(f"OpenAI SDK unavailable: {exc}") from exc`

#### `apps/voice/chat.py`

*48 references found. Showing first 5:*

- Line 1: `# apps/voice/chat.py`
- Line 2: `"""Chat backends for conversational responses."""`
- Line 30: `endpoint: str | None = None  # np. "/api/chat"`
- Line 47: `self.logger = logger or voice_logging.get_logger("voice.chat")`
- Line 104: `if backend == "openai":`

#### `apps/voice/cli.py`

- Line 6: `* stream → asr/chat/tts.transport = "realtime"`
- Line 7: `* file   → asr/chat/tts.transport = "file"`
- Line 149: `if getattr(args, "chat", None):`
- Line 150: `overrides = _merge(overrides, voice_config.override_from_pairs("chat", args.chat))`
- Line 159: `{"asr": {"transport": "realtime"}, "chat": {"transport": "realtime"}, "tts": {"transport": "realtime...`
- Line 163: `overrides, {"asr": {"transport": "file"}, "chat": {"transport": "file"}, "tts": {"transport": "file"...`

#### `apps/voice/cli_commands.py`

- Line 43: `listen.add_argument("--chat", nargs="*")`
- Line 59: `ptt.add_argument("--chat", nargs="*")`
- Line 76: `once.add_argument("--chat", nargs="*")`
- Line 223: `for section in ["asr", "chat", "tts"]:`
- Line 280: `"chat": {"transport": "realtime"},`
- Line 288: `"chat": {"transport": "file"},`
- Line 294: `for section in ["asr", "chat", "tts", "vad", "turn", "playback", "capture", "service"]:`

#### `apps/voice/common.py`

- Line 53: `Zwraca klucz OpenAI z env: OPENAI_API_KEY lub OPENAI_KEY.`
- Line 63: `"openai.key.missing",`

#### `apps/voice/config.py`

- Line 100: `override_from_pairs("chat", ["transport=realtime", "max_tokens=120"])`

#### `apps/voice/config_loader.py`

- Line 19: `"""Normalizuje wartości backendów (lower-case, alias 'gemini' -> 'google')."""`
- Line 21: `for sec in ("asr", "chat", "tts", "nlu", "playback"):`
- Line 25: `if b == "gemini":`
- Line 86: `# literówka/zmiana nazwy w sekcji chat: mode -> model`
- Line 87: `("chat", "mode"): ("chat", "model"),`
- Line 96: `"chat": {"backend", "model", "language", "system_prompt", "base_url", "endpoint", "timeout", "provid...`
- Line 148: `"asr": {"openai", "google", "local"},`
- Line 149: `"chat": {"openai", "google", "local"},`
- Line 150: `"tts": {"openai", "google", "local"},`
- Line 151: `"nlu": {"passthrough", "dummy", "openai"},`

#### `apps/voice/env_loader.py`

- Line 8: `"OPENAI_BASE": "https://api.openai.com/v1",`
- Line 9: `"OPENAI_REALTIME_ENDPOINT": ("wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview"),`

#### `apps/voice/nlu.py`

- Line 2: `""" "NLU routing: command or chat."""`
- Line 51: `return Intent(kind="chat", payload={"text": text})`
- Line 56: `self.logger.event("nlu.chat")`
- Line 57: `return Intent(kind="chat", payload={"text": normalized})`

#### `apps/voice/rt_protocol.py`

- Line 6: `Provides functions to build and validate OpenAI Realtime API messages:`
- Line 125: `"input_audio_transcription": {"model": "whisper-1"},`

#### `apps/voice/service.py`

- Line 11: `- Shimy: punkty do monkeypatch w testach (ASR, VAD, hotword/PTT, NLU/chat).`
- Line 65: `"OPENAI_API_KEY",  # Realtime / Chat`
- Line 127: `"""(shim) Punkt patchowania dla NLU/chat."""`

#### `apps/voice/session_prefs.py`

- Line 87: `cfg_chat = (config or {}).get("chat", {}) or {}`
- Line 96: `# Instructions (system prompt) - prefer stream.instructions over chat.system_prompt`
- Line 120: `# Temperature (from chat config)`
- Line 129: `# Max tokens (from chat config)`
- Line 181: `"input_audio_transcription": {"model": "whisper-1"},`

#### `apps/voice/stream/handlers.py`

- Line 23: `from ..chat import ChatSession`
- Line 146: `raise RuntimeError("Missing OpenAI API key. Configure stream.auth or set OPENAI_API_KEY.")`
- Line 369: `"""ASR→CHAT→TTS local pipeline as a fallback/augmentation."""`
- Line 375: `self.logger.event("chat.stream.start", text=transcript)`

#### `apps/voice/stream/svc_streaming.py`

- Line 26: `from ..chat import ChatConfig, ChatSession`
- Line 221: `# Chat configuration for streaming mode`
- Line 222: `chat_in = dict(self.config.get("chat", {}) or {})`
- Line 224: `backend=chat_in.get("backend", "openai"),`
- Line 225: `model=chat_in.get("model", "gpt-4o-mini"),`
- Line 236: `backend=tts_in.get("backend", "openai"),`
- Line 238: `model=tts_in.get("model", "gpt-4o-mini-tts"),`

#### `apps/voice/stream/transport.py`

- Line 100: `headers.append(("OpenAI-Beta", "realtime=v1"))`
- Line 114: `hdr_list.append("OpenAI-Beta: realtime=v1")`

#### `apps/voice/svc_core.py`

- Line 24: `chat_cfg = cfg.get("chat", {}) or {}`
- Line 63: `- 'realtime' jeśli którakolwiek z sekcji asr/chat/tts ma transport='realtime'`

#### `apps/voice/svc_file.py`

*13 references found. Showing first 5:*

- Line 6: `- Ten moduł uruchamia wyłącznie ścieżkę plikową (ASR/CHAT/TTs = "file").`
- Line 8: `- Przed uruchomieniem wymuszamy "file" w asr/chat/tts, aby uniknąć niespójności.`
- Line 32: `from .chat import ChatConfig, ChatSession`
- Line 65: `for sec in ("asr", "chat", "tts"):`
- Line 74: `"""Ustaw transport='file' w asr/chat/tts, jeśli nie ustawiono inaczej."""`

#### `apps/voice/tts.py`

*28 references found. Showing first 5:*

- Line 25: `backend: str = "openai"  # "openai" | "google" | "local"`
- Line 27: `model: str | None = None  # np. "gpt-4o-mini-tts" / "gemini-2.5-flash-preview-tts"`
- Line 199: `backend = (config.backend or "openai").lower()`
- Line 201: `# Streaming obsługujemy tylko dla OpenAI; dla Google/local pomijamy ścieżkę stream`
- Line 203: `should_start_stream = accumulate and backend == "openai"`

#### `apps/voice/web.py`

- Line 520: `JSON in: { "text": "...", "backend|provider": "openai|gemini|local|piper", "format": "wav|mp3", "voi...`
- Line 554: `# 2) Pozostałe kanały – OpenAI/Gemini`


### config/

#### `config/voice.toml`

- Line 42: `[chat]`
- Line 45: `endpoint = "/api/chat"`

#### `config/voice_gemini_example.toml`

*12 references found. Showing first 5:*

- Line 1: `# Przykładowa konfiguracja Google Gemini dla Rider-Pi`
- Line 4: `# === GOOGLE GEMINI - TRYB PLIKOWY (REST) ===`
- Line 18: `backend = "openai"`
- Line 19: `model = "whisper-1"`
- Line 23: `[chat]`

#### `config/voice_gemini_file.toml`

- Line 3: `# Google Gemini (ASR + Chat + TTS) – tryb plikowy`
- Line 20: `model    = "gemini-2.5-flash"`
- Line 23: `[chat]`
- Line 25: `model         = "gemini-2.5-flash"`
- Line 31: `model   = "gemini-2.5-flash-preview-tts"`
- Line 36: `backend        = "passthrough"  # dozwolone: dummy | openai | passthrough`
- Line 38: `llm_model      = "gemini-2.5-flash"`

#### `config/voice_local_file.toml`

- Line 20: `[chat]`
- Line 28: `endpoint = "/api/chat"`

#### `config/voice_openai_file.toml`

- Line 3: `# OpenAI (ASR + Chat + TTS) – tryb plikowy`
- Line 19: `backend  = "openai"`
- Line 20: `model    = "whisper-1"`
- Line 23: `[chat]`
- Line 24: `backend       = "openai"`
- Line 25: `model         = "gpt-4o-mini"`
- Line 30: `backend = "openai"`
- Line 35: `backend        = "openai"      # dozwolone: dummy | openai | passthrough`
- Line 37: `llm_model      = "gpt-4o-mini"`

#### `config/voice_openai_streaming.toml`

- Line 3: `# Tryb STREAMING (PTT) — pełny duplex przez WebSocket (ASR+CHAT+TTS).`
- Line 13: `endpoint = "wss://api.openai.com/v1/realtime?model=gpt-4o"`
- Line 46: `# --- ASR / CHAT / TTS – WS realtime ----------------------------------------`
- Line 48: `backend   = "openai"`
- Line 50: `model     = "gpt-4o"`
- Line 52: `[chat]`
- Line 53: `backend       = "openai"`
- Line 54: `model         = "gpt-4o"`
- Line 67: `llm_model      = "gpt-4o-mini"`

#### `config/voice_openai_streaming_fallback.toml`

- Line 15: `backend  = "openai"`
- Line 16: `model    = "whisper-1"`
- Line 24: `[chat]`
- Line 25: `backend       = "openai"`
- Line 26: `model         = "gpt-4o-mini"`
- Line 31: `backend = "openai"`
- Line 32: `model   = "gpt-4o-mini-tts"`
- Line 48: `endpoint = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview"`


### scripts/

#### `scripts/demo/config_validation.py`

- Line 61: `overrides={"asr": {"backedn": "openai"}, "unknown_section": {"key": "val"}},`

#### `scripts/demo/streaming.py`

- Line 7: `without requiring an actual OpenAI API key or WebSocket connection.`
- Line 35: `print(f"   Chat transport: {cfg_file['chat'].get('transport', 'default')}")`
- Line 47: `print(f"   Chat transport: {cfg_stream['chat'].get('transport', 'default')}")`
- Line 62: `"endpoint": "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview",`
- Line 87: `"asr": {"backend": "openai", "transport": "realtime"},`
- Line 88: `"chat": {"backend": "openai", "transport": "realtime"},`
- Line 89: `"tts": {"backend": "openai", "transport": "realtime"},`
- Line 155: `print("\nTo test with real OpenAI API:")`

#### `scripts/dev/robot_dev.sh`

- Line 2: `# robot_dev.sh — dev launcher (broker | voice | chat | face | nlu | tts2face | all | restart | stop ...`
- Line 17: `: "${VOICE_STANDALONE:=0}"   # przy all: 0 => uruchom też chat`
- Line 32: `robot_dev.sh chat          # uruchom chat   (FG)`
- Line 37: `robot_dev.sh all           # broker + voice + (chat gdy VOICE_STANDALONE=0) + face`
- Line 75: `say "start: chat"`
- Line 77: `python3 -m apps.chat.main`
- Line 107: `"apps.chat" \`
- Line 161: `run_bg chat   "env BUS_HOST='$BUS_HOST' BUS_PUB='$BUS_PUB' BUS_SUB='$BUS_SUB' python3 -m apps.chat.m...`
- Line 171: `chat)       start_chat ;;`

#### `scripts/diag_websocket-probe.py`

- Line 9: `"OPENAI_REALTIME_ENDPOINT", "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-...`
- Line 13: `"OpenAI-Beta": "realtime=v1",`

#### `scripts/sys_voice-run.sh`

- Line 13: `#   ./voice-run.sh standalone  # wymuś tryb STANDALONE (mowa + chat w voice)`
- Line 18: `# ── Klucz OpenAI z ~/.bash_profile (bezpiecznie) ──────────────────────────────`

#### `scripts/sys_voice-stream.sh`

- Line 2: `# voice_stream_chat.sh — configure environment, free audio devices and run a realtime chat demo.`
- Line 18: `: "${OPENAI_BASE:=https://api.openai.com/v1}"`
- Line 19: `: "${OPENAI_REALTIME_ENDPOINT:=wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview}"`
- Line 67: `# --- run realtime chat demo ---------------------------------------------------`
- Line 68: `echo "[voice.ops] Starting realtime chat demo..."`
- Line 140: `echo "[voice.ops] Realtime chat demo finished successfully."`
- Line 142: `echo "[voice.ops] Realtime chat demo failed with status ${STATUS}." >&2`


### services/

#### `services/api_core/chat_glue.py`

- Line 158: `Trzymamy literalne ścieżki, żeby `grep '/api/chat'` je widział.`
- Line 161: `if "/api/chat/history" not in rules:`
- Line 162: `app.add_url_rule("/api/chat/history", view_func=chat_history, methods=["GET", "OPTIONS"])`
- Line 163: `if "/api/chat/send" not in rules:`
- Line 164: `app.add_url_rule("/api/chat/send", view_func=chat_send, methods=["POST", "OPTIONS"])`
- Line 165: `# Alias kompatybilności dla starszych frontów: POST /api/chat`
- Line 166: `if "/api/chat" not in rules:`
- Line 167: `app.add_url_rule("/api/chat", view_func=chat_send, methods=["POST", "OPTIONS"])`

#### `services/api_core/local_chat.py`

- Line 3: `# tu Twoja logika lokalnego agenta (np. RAG, heurystyki, Python LLM, itp.)`

#### `services/api_server.py`

*15 references found. Showing first 5:*

- Line 344: `"""Krótka trasa /chat → web/chat.html bez 30x."""`
- Line 345: `chat_path = os.path.join(STATIC_WEB_DIR, "chat.html")`
- Line 358: `_add_rule("/chat", view_func=serve_chat, methods=["GET"], strict_slashes=False)  # no-redirect, no s...`
- Line 419: `# ── CHAT bootstrap ───────────────────────────────────────────────────────────`
- Line 424: `app.logger.info("[chat] blueprint/handlers registered via chat_api.register(app)")`


### tests/

#### `tests/config/test_config_loader.py`

*12 references found. Showing first 5:*

- Line 42: `assert "chat" in config`
- Line 49: `assert config["asr"]["backend"] == "openai"`
- Line 92: `"voice_openai_file.toml", overrides={"asr": {"unknown_field": "test"}, "chat": {"another_unknown": 1...`
- Line 102: `assert "chat.another_unknown" in unknown_strs`
- Line 157: `overrides={"capture": {"sample_rate": 24000}, "playback": {"volume": 75}, "asr": {"model": "whisper-...`

#### `tests/test_chat_gemini.py`

*13 references found. Showing first 5:*

- Line 1: `"""Tests for Google Gemini chat integration."""`
- Line 11: `"Skipping strict Gemini/OpenAI key/SDK tests by default (set RUN_STRICT_GEMINI_TESTS=1 to run).",`
- Line 22: `from apps.voice.chat import ChatConfig, ChatError, ChatSession`
- Line 26: `"""Test that Gemini backend requires GOOGLE_API_KEY."""`
- Line 29: `model="gemini-pro",`

#### `tests/test_chat_streaming.py`

- Line 1: `"""Tests for streaming chat functionality."""`
- Line 7: `from apps.voice.chat import ChatConfig, ChatSession`
- Line 12: `"""Test streaming chat with echo backend."""`
- Line 15: `model="gpt-4o-mini",`
- Line 33: `"""Test that streaming chat maintains history correctly."""`

#### `tests/test_gemini_asr_tts.py`

*23 references found. Showing first 5:*

- Line 1: `"""Tests for Google Gemini ASR and TTS integration."""`
- Line 38: `"""Tests for Gemini ASR backend."""`
- Line 41: `"""Test that Gemini ASR requires GOOGLE_API_KEY."""`
- Line 42: `config = ASRConfig(backend="google", model="gemini-1.5-flash")`
- Line 55: `"""Test that Gemini ASR requires google-generativeai SDK."""`

#### `tests/test_session_prefs.py`

- Line 17: `"chat": {},`
- Line 82: `"chat": {"temperature": 0.7},`
- Line 95: `"chat": {"max_tokens": 150},`
- Line 108: `"chat": {"system_prompt": "Default prompt"},`
- Line 118: `"""Test building session preferences using chat.system_prompt as fallback."""`
- Line 121: `"chat": {"system_prompt": "I am Rider-Pi."},`
- Line 142: `"chat": {"tools": tools, "tool_choice": "auto"},`
- Line 193: `assert result["input_audio_transcription"]["model"] == "whisper-1"`
- Line 246: `"chat": {"temperature": "invalid"},`
- Line 259: `"chat": {"max_tokens": "invalid"},`

#### `tests/test_tts_streaming.py`

- Line 15: `backend="openai",`
- Line 17: `model="gpt-4o-mini-tts",`

#### `tests/test_voice_cli_streaming.py`

*41 references found. Showing first 5:*

- Line 5: `- Parses --chat arguments`
- Line 24: `"""Test that CLI parser accepts --chat arguments."""`
- Line 28: `args = parser.parse_args(['listen', '--chat', 'transport=realtime', 'max_tokens=100'])`
- Line 29: `assert hasattr(args, 'chat')`
- Line 30: `assert args.chat == ['transport=realtime', 'max_tokens=100']`

#### `tests/test_voice_integration.py`

- Line 35: `"asr": {"backend": "openai", "transport": "file"},`
- Line 36: `"chat": {"backend": "openai", "transport": "rest"},`
- Line 37: `"tts": {"backend": "openai", "transport": "file"},`
- Line 43: `"asr": {"backend": "openai", "transport": "realtime"},`
- Line 52: `"chat": {"backend": "openai", "transport": "realtime"},`
- Line 86: `"tts": {"backend": "openai", "transport": "realtime"},`
- Line 89: `"endpoint": "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview",`
- Line 133: `"chat": {"transport": "rest"},`

#### `tests/test_voice_service_ui_state.py`

- Line 67: `"chat": {"backend": "echo", "model": "dummy", "system_prompt": "", "max_history": 1},`

#### `tests/test_voice_stream_smoke.py`

- Line 48: `"endpoint": "wss://api.openai.com/v1/realtime",`

#### `tests/test_voice_streaming.py`

- Line 72: `"asr": {"backend": "openai", "transport": "realtime", "language": "pl"},`
- Line 73: `"chat": {`
- Line 74: `"backend": "openai",`
- Line 79: `"tts": {"backend": "openai", "transport": "realtime", "voice": "ash"},`
- Line 82: `"endpoint": "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview",`

#### `tests/test_web_routes.py`

- Line 7: `- GET /chat → 200   (jeśli serwowane jako /web/chat.html – testuje plik)`
- Line 72: `"""Test that /web/chat.html exists (static chat page)."""`
- Line 76: `r = c.get("/web/chat.html")`
- Line 77: `assert r.status_code == 200, f"Expected 200 for /web/chat.html, got {r.status_code}"`


---

## ASR (Automatic Speech Recognition)

**Files with ASR (Automatic Speech Recognition) references**: 31

### apps/

#### `apps/voice/asr.py`

*30 references found. Showing first 5:*

- Line 1: `# apps/voice/asr.py`
- Line 2: `"""Automatic speech recognition backends."""`
- Line 23: `backend: str = "openai"  # "openai" | "google" | "vosk" | "local"`
- Line 36: `endpoint: str | None = None  # np. "/api/asr"`
- Line 87: `def transcribe(`

#### `apps/voice/cli.py`

*12 references found. Showing first 5:*

- Line 6: `* stream → asr/chat/tts.transport = "realtime"`
- Line 7: `* file   → asr/chat/tts.transport = "file"`
- Line 142: `- --vad trafia do asr.vad (wcześniej było top-level 'vad')`
- Line 147: `if getattr(args, "asr", None):`
- Line 148: `overrides = _merge(overrides, voice_config.override_from_pairs("asr", args.asr))`

#### `apps/voice/cli_commands.py`

*17 references found. Showing first 5:*

- Line 22: `from .asr import ASRConfig, transcribe`
- Line 33: `parser.add_argument("--lang", type=str, help="ASR language hint (pl|en|auto)", default=None)`
- Line 42: `listen.add_argument("--asr", nargs="*")`
- Line 58: `ptt.add_argument("--asr", nargs="*")`
- Line 75: `once.add_argument("--asr", nargs="*")`

#### `apps/voice/config.py`

- Line 99: `override_from_pairs(["asr.backend=vosk", "tts.rate=1.1"])`

#### `apps/voice/config_loader.py`

- Line 21: `for sec in ("asr", "chat", "tts", "nlu", "playback"):`
- Line 79: `ALLOWED_HOTWORD_ENGINES = {"porcupine", "ptt", "vosk", "none"}`
- Line 95: `"asr": {"backend", "model", "language", "base_url", "endpoint", "content_type", "timeout", "provider...`
- Line 148: `"asr": {"openai", "google", "local"},`

#### `apps/voice/local_io.py`

- Line 2: `# Rider-Pi: lokalny backend głosowy (TTS Piper + ASR Vosk)`
- Line 19: `# ASR (Vosk)`
- Line 21: `# pip install vosk`
- Line 22: `from vosk import KaldiRecognizer, Model  # type: ignore`
- Line 69: `"""Lekki wrapper na Vosk – rozpoznaje z WAV/PCM."""`
- Line 73: `raise RuntimeError("vosk module not available (pip install vosk)")`
- Line 89: `# Vosk najlepiej mono – prosty downmix (L)`

#### `apps/voice/service.py`

- Line 11: `- Shimy: punkty do monkeypatch w testach (ASR, VAD, hotword/PTT, NLU/chat).`
- Line 96: `# Elastyczny import transcribe_file -> transcribe`
- Line 98: `# wariant: apps/asr.py (poza pakietem voice)`
- Line 99: `from ..asr import transcribe_file as transcribe  # type: ignore[attr-defined]`
- Line 102: `# wariant: apps/voice/asr.py (wewnątrz pakietu voice)`
- Line 103: `from .asr import transcribe_file as transcribe  # type: ignore[attr-defined]`
- Line 106: `def transcribe(*args, **kwargs):  # type: ignore[no-redef]`
- Line 108: `raise NotImplementedError("transcribe shim: brak modułu asr.py (apps/asr.py lub apps/voice/asr.py)")`
- Line 141: `"transcribe",`

#### `apps/voice/stream/handlers.py`

- Line 339: `# ── ASR (serwerowa transkrypcja) ─────────────────────────────────`
- Line 343: `self.logger.event("asr.transcript.final", text=transcript)`
- Line 369: `"""ASR→CHAT→TTS local pipeline as a fallback/augmentation."""`

#### `apps/voice/svc_core.py`

- Line 23: `asr_cfg = cfg.get("asr", {}) or {}`
- Line 63: `- 'realtime' jeśli którakolwiek z sekcji asr/chat/tts ma transport='realtime'`

#### `apps/voice/svc_file.py`

- Line 6: `- Ten moduł uruchamia wyłącznie ścieżkę plikową (ASR/CHAT/TTs = "file").`
- Line 8: `- Przed uruchomieniem wymuszamy "file" w asr/chat/tts, aby uniknąć niespójności.`
- Line 29: `from .asr import ASRConfig, Transcript, transcribe`
- Line 65: `for sec in ("asr", "chat", "tts"):`
- Line 74: `"""Ustaw transport='file' w asr/chat/tts, jeśli nie ustawiono inaczej."""`
- Line 169: `# ASR`
- Line 171: `asr_in = _merge_defaults(config.get("asr"), asr_defaults)`
- Line 406: `transcript = transcribe(audio, self._capture_cfg.sample_rate, self._asr_cfg, self.logger)`
- Line 407: `self.logger.event("service.asr.transcript", text=transcript.text)`

#### `apps/voice/web.py`

- Line 36: `# Opcjonalne lokalne backendy (Piper / Vosk) – importy „best-effort”`
- Line 52: `from vosk import KaldiRecognizer, Model  # type: ignore  # pip install vosk`
- Line 67: `# Vosk`
- Line 68: `VOSK_MODEL = os.getenv("VOSK_MODEL", "/home/pi/robot/models/vosk/vosk-model-small-pl-0.22")`
- Line 107: `"""Zwraca vosk.Model (singleton) lub podnosi RuntimeError, gdy brak modułu/modelu."""`
- Line 109: `raise RuntimeError("vosk module not available (pip install vosk)")`
- Line 113: `raise RuntimeError(f"Vosk model not found dir: {VOSK_MODEL}")`
- Line 610: `# Lokalny ASR (Vosk) – przyjmuje WAV (lub MP3/OGG), zwraca JSON`
- Line 614: `@app.post("/api/asr")`
- Line 622: `return jsonify({"ok": False, "error": "vosk module not available"}), 500`


### common/

#### `common/nlu_shared.py`

- Line 24: `# popularne literówki / warianty z ASR`


### config/

#### `config/voice.toml`

- Line 34: `[asr]`
- Line 37: `endpoint = "/api/asr"`

#### `config/voice_gemini_example.toml`

- Line 17: `[asr]`
- Line 59: `# export OPENAI_API_KEY="twój-klucz-openai"  # dla ASR i TTS`

#### `config/voice_gemini_file.toml`

- Line 3: `# Google Gemini (ASR + Chat + TTS) – tryb plikowy`
- Line 18: `[asr]`

#### `config/voice_local_file.toml`

- Line 12: `[asr]`
- Line 15: `endpoint = "/api/asr"`

#### `config/voice_openai_file.toml`

- Line 3: `# OpenAI (ASR + Chat + TTS) – tryb plikowy`
- Line 18: `[asr]`

#### `config/voice_openai_streaming.toml`

- Line 3: `# Tryb STREAMING (PTT) — pełny duplex przez WebSocket (ASR+CHAT+TTS).`
- Line 46: `# --- ASR / CHAT / TTS – WS realtime ----------------------------------------`
- Line 47: `[asr]`

#### `config/voice_openai_streaming_fallback.toml`

- Line 14: `[asr]`


### scripts/

#### `scripts/demo/config_validation.py`

- Line 61: `overrides={"asr": {"backedn": "openai"}, "unknown_section": {"key": "val"}},`
- Line 83: `_ = loader.load("voice_openai_file.toml", overrides={"asr": {"unknown_key": "test"}, "bad_section": ...`
- Line 115: `loader.load("voice_openai_file.toml", overrides={"asr": {"backend": "invalid"}})`
- Line 119: `print("✓ Rejected invalid ASR backend")`

#### `scripts/demo/streaming.py`

- Line 34: `print(f"   ASR transport: {cfg_file['asr'].get('transport', 'default')}")`
- Line 46: `print(f"   ASR transport: {cfg_stream['asr'].get('transport', 'default')}")`
- Line 87: `"asr": {"backend": "openai", "transport": "realtime"},`

#### `scripts/talk_assistant.sh`

- Line 16: `TXT=$(curl -s -X POST 'http://127.0.0.1:8092/api/asr' \`
- Line 18: `echo "[ASR] >> $TXT"`

#### `scripts/talk_local.sh`

- Line 8: `echo "[ASR] Rozpoznaję…"`
- Line 9: `TXT=$(curl -s -X POST 'http://127.0.0.1:8092/api/asr' \`
- Line 12: `echo "[ASR] >> $TXT"`


### services/

#### `services/api_core/voice_local_proxy.py`

- Line 134: `# ASR: 8080 → (proxy) → 8092`
- Line 151: `url = f"{VOICE_WEB_BASE}/api/asr"`
- Line 168: `return _cors(jsonify({"ok": False, "error": f"voice asr http error: {status}", "body": snippet})), 5...`
- Line 188: `return _cors(jsonify({"ok": False, "error": f"voice asr http error: {e.code}", "body": err_body[:800...`
- Line 190: `return _cors(jsonify({"ok": False, "error": f"voice asr proxy failed: {e}"})), 502`

#### `services/api_server.py`

- Line 167: `_add_rule("/api/voice/asr", view_func=voice_local_proxy.asr_local_handler, methods=["POST", "OPTIONS...`


### tests/

#### `tests/config/test_config_loader.py`

*15 references found. Showing first 5:*

- Line 41: `assert "asr" in config`
- Line 49: `assert config["asr"]["backend"] == "openai"`
- Line 77: `"asr": {"devicee": "typo"},  # Typo: devicee instead of device`
- Line 84: `assert "asr.devicee" in error_msg.lower()`
- Line 92: `"voice_openai_file.toml", overrides={"asr": {"unknown_field": "test"}, "chat": {"another_unknown": 1...`

#### `tests/test_gemini_asr_tts.py`

- Line 1: `"""Tests for Google Gemini ASR and TTS integration."""`
- Line 14: `from apps.voice.asr import ASRConfig, ASRError, transcribe`
- Line 38: `"""Tests for Gemini ASR backend."""`
- Line 41: `"""Test that Gemini ASR requires GOOGLE_API_KEY."""`
- Line 49: `transcribe(audio, 16000, config)`
- Line 55: `"""Test that Gemini ASR requires google-generativeai SDK."""`
- Line 69: `"""Test successful Gemini ASR transcription."""`
- Line 82: `result = transcribe(audio, 16000, config)`
- Line 92: `"""Test that Gemini ASR handles API errors properly."""`

#### `tests/test_voice_cli_streaming.py`

- Line 59: `"asr": {"backend": "openai", "transport": "file"},`
- Line 71: `"asr": {"backend": "openai", "transport": "realtime"},`
- Line 93: `"asr": {"backend": "openai"},`
- Line 113: `"asr": {"transport": "realtime"},`
- Line 136: `"asr": {"transport": "file"},`
- Line 155: `config = {"asr": {"transport": "realtime"}}`
- Line 205: `# Only ASR is realtime - should trigger streaming`
- Line 276: `"asr": {"backend": "openai", "model": "whisper"},`
- Line 281: `"asr": {"backend": "openai", "unknown_field": "test"},`
- Line 289: `assert "WARNING: unknown config key 'asr.unknown_field'" in captured.out`

#### `tests/test_voice_integration.py`

- Line 35: `"asr": {"backend": "openai", "transport": "file"},`
- Line 43: `"asr": {"backend": "openai", "transport": "realtime"},`
- Line 132: `"asr": {"transport": "realtime"},`
- Line 149: `"asr": {"transport": "file"},`

#### `tests/test_voice_service_ui_state.py`

- Line 25: `from .asr import transcribe`
- Line 28: `i potem używa lokalnych nazw modułu (svc_file.transcribe itd.).`
- Line 48: `# Lokalne Transcript (żeby test nie musiał importować z apps.voice.asr)`
- Line 78: `"asr": {"backend": "dummy", "model": "dummy", "language": "en"},`
- Line 114: `- service_impl.transcribe -> Transcript(transcribe_text)`
- Line 119: `monkeypatch.setattr(service_impl_mod, "transcribe", lambda *a, **k: Transcript(text=transcribe_text,...`
- Line 146: `_patch_runtime(monkeypatch, service_impl_mod, transcribe_text="ok")  # ASR OK, ale odpowiedź będzie ...`

#### `tests/test_voice_streaming.py`

- Line 72: `"asr": {"backend": "openai", "transport": "realtime", "language": "pl"},`


---

## TTS (Text-to-Speech)

**Files with TTS (Text-to-Speech) references**: 50

### apps/

#### `apps/chat/main.py`

- Line 5: `apps/chat/main.py — Chat: audio.transcript -> (OpenAI) -> tts.speak`
- Line 95: `log("CHAT: start (sub audio.transcript -> pub tts.speak)")`
- Line 111: `PUB.publish("tts.speak", {"text": ans, "ts": now_ts(), "source": "chat"})`
- Line 112: `log(f"CHAT -> TTS: {ans}")`

#### `apps/draw/face_primitives.py`

- Line 271: `if getattr(model, "assist_speaking", False) or getattr(model, "state", "") == "speak":`

#### `apps/ui/face/controller.py`

- Line 116: `def speak(self, on: bool = True) -> None:`

#### `apps/voice/cli.py`

- Line 6: `* stream → asr/chat/tts.transport = "realtime"`
- Line 7: `* file   → asr/chat/tts.transport = "file"`
- Line 29: `from .tts import TTSConfig, synthesize`
- Line 151: `if getattr(args, "tts", None):`
- Line 152: `overrides = _merge(overrides, voice_config.override_from_pairs("tts", args.tts))`
- Line 159: `{"asr": {"transport": "realtime"}, "chat": {"transport": "realtime"}, "tts": {"transport": "realtime...`
- Line 163: `overrides, {"asr": {"transport": "file"}, "chat": {"transport": "file"}, "tts": {"transport": "file"...`
- Line 378: `Normalizuje wyjście synthesize(...):`
- Line 382: `audio, sample_rate, fmt = synthesize(text, TTSConfig(**_filter_for_dataclass(tts_cfg, TTSConfig)))`
- Line 470: `"""Execute TTS command (delegated to cli_commands module)."""`

#### `apps/voice/cli_commands.py`

*15 references found. Showing first 5:*

- Line 24: `from .tts import TTSConfig, synthesize`
- Line 44: `listen.add_argument("--tts", nargs="*")`
- Line 60: `ptt.add_argument("--tts", nargs="*")`
- Line 77: `once.add_argument("--tts", nargs="*")`
- Line 94: `# TTS command`

#### `apps/voice/config.py`

- Line 99: `override_from_pairs(["asr.backend=vosk", "tts.rate=1.1"])`

#### `apps/voice/config_loader.py`

- Line 21: `for sec in ("asr", "chat", "tts", "nlu", "playback"):`
- Line 97: `"tts": {"backend", "model", "format", "voice", "base_url", "endpoint", "accept", "timeout", "provide...`
- Line 150: `"tts": {"openai", "google", "local"},`

#### `apps/voice/kws.py`

- Line 157: `prompt: str = "[voice] Press ENTER to speak…",`

#### `apps/voice/local_io.py`

- Line 2: `# Rider-Pi: lokalny backend głosowy (TTS Piper + ASR Vosk)`
- Line 10: `# TTS (Piper)`
- Line 12: `# pip install piper-tts`
- Line 13: `import piper  # type: ignore`
- Line 36: `sample_rate: int = 22050  # Piper zwykle generuje 22.05 kHz`
- Line 46: `"""Lekki wrapper na Piper – generuje WAV w pamięci."""`
- Line 50: `raise RuntimeError("piper module not available (pip install piper-tts)")`
- Line 52: `self._tts = piper.PiperVoice(cfg.model_path)`
- Line 57: `# piper generuje PCM 16-bit LE; zapiszmy jako prawidłowy WAV`
- Line 58: `pcm = self._tts.synthesize(`

#### `apps/voice/piper_compat.py`

- Line 4: `from piper.voice import PiperVoice`
- Line 25: `voice.synthesize(`

#### `apps/voice/rt_protocol.py`

- Line 82: `voice: TTS voice to use (default: verse)`

#### `apps/voice/session_prefs.py`

- Line 8: `- Language and TTS voice`
- Line 43: `voice: TTS voice name (e.g., "verse", "ash", "alloy")`
- Line 88: `cfg_tts = (config or {}).get("tts", {}) or {}`
- Line 93: `# Voice (TTS)`

#### `apps/voice/stream/handlers.py`

- Line 24: `from ..tts import TTSConfig`
- Line 369: `"""ASR→CHAT→TTS local pipeline as a fallback/augmentation."""`
- Line 371: `from ..tts import speak_stream`
- Line 383: `self.logger.event("tts.stream.start")`

#### `apps/voice/stream/playout.py`

- Line 2: `"""Audio capture and TTS playback worker threads for streaming voice service.`
- Line 6: `- TTS playback (queue → audio output)`
- Line 23: `"""Mixin providing audio capture and TTS playback workers for StreamingVoiceService."""`
- Line 68: `# barge-in: wyczyść TTS, jeśli aktywny`
- Line 89: `# TTS playback worker`
- Line 92: `"""Start TTS player thread."""`
- Line 114: `self.logger.event("tts.stream.close_error", error=str(e))`
- Line 124: `self.logger.event("tts.stream.start_error", error=str(e))`
- Line 131: `self.logger.event("tts.stream.write_error", error=str(e))`
- Line 144: `self._tts_player_thread = threading.Thread(target=player_target, name="stream-tts-player", daemon=Tr...`

#### `apps/voice/stream/state.py`

- Line 24: `SPEAKING = auto()  # Playing TTS response`
- Line 38: `TTS_START = auto()  # TTS playback started`
- Line 39: `TTS_COMPLETE = auto()  # TTS playback finished`
- Line 231: `"""Check if currently playing TTS."""`

#### `apps/voice/stream/svc_streaming.py`

- Line 9: `- StreamPlayoutMixin: Audio capture and TTS playback workers`
- Line 30: `from ..tts import TTSConfig`
- Line 233: `# TTS configuration for streaming mode`
- Line 234: `tts_in = dict(self.config.get("tts", {}) or {})`
- Line 238: `model=tts_in.get("model", "gpt-4o-mini-tts"),`
- Line 244: `# Playback configuration for TTS`
- Line 348: `async def once(self, *, speak: bool = True) -> dict[str, Any] | None:`
- Line 361: `if speak:`

#### `apps/voice/stream_chunks.py`

- Line 74: `tts_cfg = (config or {}).get("tts", {}) or {}`

#### `apps/voice/svc_audio.py`

- Line 239: `"""Play TTS result; respects volume and post_tts_mute_ms.`
- Line 241: `Placeholder – odtwarzanie TTS jest obsługiwane przez warstwę „speech worker”.`

#### `apps/voice/svc_bus.py`

- Line 2: `"""Bus integration for voice service (UI state publishing and TTS speak subscription)."""`
- Line 24: `"""Mixin providing bus publishing and TTS speak subscription for VoiceService."""`
- Line 74: `# TTS speak loop (bus subscription)`
- Line 77: `"""Subscribe to tts.speak bus topic and queue speech tasks."""`

#### `apps/voice/svc_core.py`

- Line 25: `tts_cfg = cfg.get("tts", {}) or {}`
- Line 63: `- 'realtime' jeśli którakolwiek z sekcji asr/chat/tts ma transport='realtime'`

#### `apps/voice/svc_file.py`

*24 references found. Showing first 5:*

- Line 6: `- Ten moduł uruchamia wyłącznie ścieżkę plikową (ASR/CHAT/TTs = "file").`
- Line 8: `- Przed uruchomieniem wymuszamy "file" w asr/chat/tts, aby uniknąć niespójności.`
- Line 37: `from .tts import TTSConfig, TTSStreamResult, speak`
- Line 65: `for sec in ("asr", "chat", "tts"):`
- Line 74: `"""Ustaw transport='file' w asr/chat/tts, jeśli nie ustawiono inaczej."""`

#### `apps/voice/tts.py`

*67 references found. Showing first 5:*

- Line 1: `# apps/voice/tts.py`
- Line 27: `model: str | None = None  # np. "gpt-4o-mini-tts" / "gemini-2.5-flash-preview-tts"`
- Line 32: `# STRICT — gdy "realtime", blokujemy wszelkie REST/HTTP TTS`
- Line 36: `endpoint: str | None = None  # np. "/api/tts"`
- Line 159: `logger.event("tts.decode.ffmpeg_failed", extra={"data": str(e)})`

#### `apps/voice/web.py`

*42 references found. Showing first 5:*

- Line 36: `# Opcjonalne lokalne backendy (Piper / Vosk) – importy „best-effort”`
- Line 64: `PIPER_MODEL_DIR = os.getenv("PIPER_MODEL_DIR", "/home/pi/robot/models/piper").rstrip("/")`
- Line 76: `"""Zwraca pełną ścieżkę do modelu Piper."""`
- Line 96: `raise RuntimeError("piper module not available (apps.voice.piper_compat.PiperVoice)")`
- Line 101: `raise RuntimeError(f"Piper model not found: {model}")`


### config/

#### `config/voice.toml`

- Line 50: `[tts]`
- Line 53: `endpoint = "/api/tts"`

#### `config/voice_gemini_example.toml`

- Line 35: `[tts]`
- Line 37: `model = "tts-1"`
- Line 59: `# export OPENAI_API_KEY="twój-klucz-openai"  # dla ASR i TTS`

#### `config/voice_gemini_file.toml`

- Line 3: `# Google Gemini (ASR + Chat + TTS) – tryb plikowy`
- Line 29: `[tts]`
- Line 31: `model   = "gemini-2.5-flash-preview-tts"`

#### `config/voice_local_file.toml`

- Line 31: `[tts]`
- Line 38: `endpoint = "/api/tts"`

#### `config/voice_openai_file.toml`

- Line 3: `# OpenAI (ASR + Chat + TTS) – tryb plikowy`
- Line 29: `[tts]`

#### `config/voice_openai_streaming.toml`

- Line 3: `# Tryb STREAMING (PTT) — pełny duplex przez WebSocket (ASR+CHAT+TTS).`
- Line 46: `# --- ASR / CHAT / TTS – WS realtime ----------------------------------------`
- Line 57: `[tts]`

#### `config/voice_openai_streaming_fallback.toml`

- Line 30: `[tts]`
- Line 32: `model   = "gpt-4o-mini-tts"`


### scripts/

#### `scripts/demo/config_validation.py`

- Line 132: `base_voice = config1["tts"]["voice"]`
- Line 135: `config2 = loader.load("voice_openai_file.toml", overrides={"tts": {"voice": "nova"}})`
- Line 136: `overridden_voice = config2["tts"]["voice"]`
- Line 138: `print(f"✓ Base TOML: tts.voice = {base_voice}")`
- Line 139: `print(f"✓ With CLI override: tts.voice = {overridden_voice}")`
- Line 205: `config = loader.load("voice_openai_file.toml", overrides={"tts": {"voice": "nova"}})`

#### `scripts/demo/streaming.py`

- Line 36: `print(f"   TTS transport: {cfg_file['tts'].get('transport', 'default')}")`
- Line 48: `print(f"   TTS transport: {cfg_stream['tts'].get('transport', 'default')}")`
- Line 89: `"tts": {"backend": "openai", "transport": "realtime"},`

#### `scripts/dev/robot_dev.sh`

- Line 35: `robot_dev.sh tts2face      # mostek tts.speak -> ui.face.set`
- Line 88: `# --- NOWE: NLU i TTS→Face ---`
- Line 96: `say "start: tts2face (bridge tts.speak -> ui.face.set)"`

#### `scripts/sys_voice-once.sh`

- Line 35: `--tts format=wav \`

#### `scripts/sys_voice-run.sh`

- Line 56: `# TTS strumieniowe (jeśli w trybie standalone)`

#### `scripts/sys_voice-stream.sh`

- Line 117: `# 3) Start PTT + handler wiadomości + TTS`
- Line 123: `# 4) Poproś o odpowiedź (bez input_audio – to demko TTS)`

#### `scripts/talk_assistant.sh`

- Line 6: `curl -s -X POST 'http://127.0.0.1:8092/api/tts' \`
- Line 8: `-d "{\"text\":\"$msg\",\"backend\":\"piper\",\"voice\":\"pl_PL-gosia-medium.onnx\"}" \`

#### `scripts/talk_local.sh`

- Line 15: `echo "[TTS] Odpowiadam…"`
- Line 16: `curl -s -X POST 'http://127.0.0.1:8092/api/tts' \`
- Line 18: `-d "{\"text\":\"$TXT\",\"backend\":\"piper\",\"voice\":\"pl_PL-gosia-medium.onnx\"}" \`
- Line 22: `echo "[TTS] Cisza (nic nie rozpoznano)."`


### services/

#### `services/api_core/voice_local_proxy.py`

- Line 36: `# TTS: 8080 → (proxy) → 8092`
- Line 53: `if provider not in ("local", "piper"):`
- Line 70: `url = f"{VOICE_WEB_BASE}/api/tts?b64=1"`
- Line 93: `return _cors(jsonify({"ok": False, "error": "tts failed", "backend": obj})), 502`
- Line 101: `r2.headers["Content-Disposition"] = "inline; filename=tts.wav"`
- Line 108: `r3.headers["Content-Disposition"] = "inline; filename=tts.wav"`
- Line 124: `"error": f"voice tts http error: {e.code}",`
- Line 130: `return _cors(jsonify({"ok": False, "error": f"voice tts proxy failed: {e}"})), 502`

#### `services/api_server.py`

- Line 166: `_add_rule("/api/voice/tts", view_func=voice_local_proxy.tts_local_handler, methods=["POST", "OPTIONS...`


### tests/

#### `tests/config/test_config_loader.py`

- Line 43: `assert "tts" in config`
- Line 50: `assert config["tts"]["format"] == "wav"`
- Line 148: `assert config_base["tts"]["voice"] == "ash"`
- Line 151: `config_overridden = loader.load("voice_openai_file.toml", overrides={"tts": {"voice": "nova"}})`
- Line 152: `assert config_overridden["tts"]["voice"] == "nova"`
- Line 286: `"tts",`

#### `tests/test_gemini_asr_tts.py`

*16 references found. Showing first 5:*

- Line 1: `"""Tests for Google Gemini ASR and TTS integration."""`
- Line 15: `from apps.voice.tts import TTSConfig, TTSError, synthesize`
- Line 108: `"""Tests for Gemini TTS backend."""`
- Line 111: `"""Test that Gemini TTS requires GOOGLE_API_KEY."""`
- Line 118: `synthesize("Hello world", config)`

#### `tests/test_session_prefs.py`

- Line 18: `"tts": {},`
- Line 39: `"""Test building session preferences with custom TTS voice."""`
- Line 43: `"tts": {"voice": "ash"},`

#### `tests/test_tts_streaming.py`

- Line 1: `"""Tests for streaming TTS functionality."""`
- Line 8: `from apps.voice.tts import TTSConfig, speak_stream`
- Line 17: `model="gpt-4o-mini-tts",`
- Line 32: `# Note: This test will try to call speak(), which requires OPENAI_API_KEY`
- Line 33: `# In a real scenario, we'd mock the speak() function`

#### `tests/test_voice_cli_streaming.py`

- Line 61: `"tts": {"backend": "openai", "transport": "file"},`
- Line 73: `"tts": {"backend": "openai", "transport": "realtime"},`
- Line 95: `"tts": {"backend": "openai"},`
- Line 115: `"tts": {"transport": "file"},`
- Line 213: `# Only TTS is realtime - should trigger streaming`
- Line 217: `"tts": {"transport": "realtime"},`

#### `tests/test_voice_integration.py`

- Line 37: `"tts": {"backend": "openai", "transport": "file"},`
- Line 86: `"tts": {"backend": "openai", "transport": "realtime"},`
- Line 134: `"tts": {"transport": "file"},`

#### `tests/test_voice_ptt_state.py`

- Line 63: `# TTS starts playing`
- Line 68: `# TTS finished`
- Line 116: `"""Test interruption during TTS playback."""`

#### `tests/test_voice_service_ui_state.py`

- Line 26: `from .tts import synthesize`
- Line 79: `"tts": {"backend": "dummy", "model": "dummy", "voice": "dummy", "format": "wav"},`
- Line 116: `- service_impl.synthesize -> (b"audio", 16000, "wav")`
- Line 121: `monkeypatch.setattr(service_impl_mod, "synthesize", lambda *a, **k: (b"audio", 16000, "wav"), raisin...`
- Line 135: `def failing_cycle(*, speak: bool = True):  # noqa: ARG001`

#### `tests/test_voice_streaming.py`

- Line 79: `"tts": {"backend": "openai", "transport": "realtime", "voice": "ash"},`
- Line 260: `# Add some TTS data to queue`
- Line 268: `# Clear TTS queue on barge-in`

#### `tests/test_voice_svc_stream_proxy.py`

- Line 25: `async def once(self, *, speak=True):`
- Line 26: `assert speak is True`
- Line 38: `result = await svc.once(speak=True)`


---

## NLU (Natural Language Understanding)

**Files with NLU (Natural Language Understanding) references**: 20

### apps/

#### `apps/chat/main.py`

- Line 104: `# jeśli to komenda ruchu — zostaw to NLU/Motion`

#### `apps/nlu/main.py`

- Line 5: `apps/nlu/main.py — NLU v0.1 (PL → motion.cmd)`
- Line 185: `log(f"NLU: speed up → {cur_speed:.2f}")`
- Line 190: `log(f"NLU: speed down → {cur_speed:.2f}")`
- Line 229: `log("NLU v0.1: start (sub audio.transcript → pub motion.cmd)")`
- Line 248: `log(f"NLU → motion.cmd: {cmd}")`
- Line 252: `log(f"NLU error: {e}")`
- Line 259: `log("NLU: bye")`

#### `apps/voice/config_loader.py`

- Line 21: `for sec in ("asr", "chat", "tts", "nlu", "playback"):`
- Line 98: `"nlu": {"backend", "chat_threshold", "llm_model", "command_keywords"},`
- Line 151: `"nlu": {"passthrough", "dummy", "openai"},`

#### `apps/voice/nlu.py`

- Line 1: `# apps/voice/nlu.py`
- Line 2: `""" "NLU routing: command or chat."""`
- Line 31: `class Intent:`
- Line 39: `base_logger = logger or voice_logging.get_logger("voice.nlu")`
- Line 48: `def route(self, text: str) -> Intent:`
- Line 51: `return Intent(kind="chat", payload={"text": text})`
- Line 54: `self.logger.event("nlu.command", command=name)`
- Line 55: `return Intent(kind="command", payload={"name": name, "text": normalized})`
- Line 56: `self.logger.event("nlu.chat")`
- Line 57: `return Intent(kind="chat", payload={"text": normalized})`

#### `apps/voice/service.py`

- Line 11: `- Shimy: punkty do monkeypatch w testach (ASR, VAD, hotword/PTT, NLU/chat).`
- Line 127: `"""(shim) Punkt patchowania dla NLU/chat."""`

#### `apps/voice/svc_file.py`

*12 references found. Showing first 5:*

- Line 35: `from .nlu import Intent, NLUConfig, NLURouter`
- Line 95: `intent: Intent`
- Line 144: `# NLU`
- Line 146: `config.get("nlu"),`
- Line 410: `intent = self._nlu.route(transcript.text)`


### common/

#### `common/nlu_shared.py`

- Line 7: `common/nlu_shared.py — wspólne funkcje NLU:`
- Line 10: `- parse_motion_intent()  — mapuje tekst na intent ruchu (dict) lub None`
- Line 105: `def confirm_text(intent: dict) -> str:`
- Line 106: `a = intent.get("action")`


### config/

#### `config/choreography.toml`

- Line 79: `# Example: NLU emotion detection (if implemented)`
- Line 82: `description = "Respond to NLU-detected joy"`
- Line 85: `topic = "events.nlu.emotion"`

#### `config/voice.toml`

- Line 61: `[nlu]`
- Line 66: `[nlu.command_keywords]`

#### `config/voice_gemini_example.toml`

- Line 42: `[nlu]`
- Line 46: `[nlu.command_keywords]`

#### `config/voice_gemini_file.toml`

- Line 35: `[nlu]`
- Line 40: `[nlu.command_keywords]`

#### `config/voice_local_file.toml`

- Line 42: `[nlu]`

#### `config/voice_openai_file.toml`

- Line 34: `[nlu]`
- Line 39: `[nlu.command_keywords]`

#### `config/voice_openai_streaming.toml`

- Line 64: `# --- NLU / HOTWORD ----------------------------------------------------------`
- Line 65: `[nlu]`
- Line 69: `[nlu.command_keywords]`

#### `config/voice_openai_streaming_fallback.toml`

- Line 18: `[nlu]`


### scripts/

#### `scripts/dev/robot_dev.sh`

- Line 2: `# robot_dev.sh — dev launcher (broker | voice | chat | face | nlu | tts2face | all | restart | stop ...`
- Line 34: `robot_dev.sh nlu           # NLU (audio.transcript -> motion.cmd)`
- Line 88: `# --- NOWE: NLU i TTS→Face ---`
- Line 90: `say "start: nlu"`
- Line 92: `python3 -m apps.nlu.main`
- Line 109: `"apps.nlu.main" \`
- Line 173: `nlu)        start_nlu ;;           # <-- NOWE`


### tests/

#### `tests/config/test_config_loader.py`

- Line 284: `"nlu",`

#### `tests/test_choreographer_integration.py`

- Line 100: `process_event("events.nlu.emotion", {"data": "test"}, mappings, pub)`

#### `tests/test_choreographer_mapping.py`

- Line 70: `event = {"sentiment": "joy", "confidence": 0.9, "source": "nlu"}`
- Line 71: `criteria = {"sentiment": "joy", "source": "nlu"}`
- Line 169: `# Should match events.nlu.emotion`
- Line 170: `process_event("events.nlu.emotion", {"type": "test"}, mappings, pub)`

#### `tests/test_voice_service_ui_state.py`

- Line 68: `"nlu": {"chat_threshold": 0.0, "command_keywords": {}, "llm_model": "dummy"},`
- Line 154: `monkeypatch.setattr(service, "_handle_intent", lambda intent: "   ")  # pusta odpowiedź`
- Line 230: `monkeypatch.setattr(service, "_handle_intent", lambda intent: "Test response")`


---

## Vision Technologies

**Files with Vision Technologies references**: 37

### apps/

#### `apps/camera/__main__.py`

- Line 24: `p.add_argument("--alpha", type=float, help="jasnosc (OpenCV convertScaleAbs alpha)")`

#### `apps/camera/cam_motion.py`

*20 references found. Showing first 5:*

- Line 63: `import cv2  # type: ignore`
- Line 64: `except Exception:  # brak OpenCV – moduł wciąż się skompiluje, ale run() nie ruszy`
- Line 65: `cv2 = None  # type: ignore`
- Line 113: `if cv2 is None:`
- Line 114: `raise RuntimeError("OpenCV nie jest zainstalowany (cv2==None)")`

#### `apps/camera/preview_lcd.py`

*42 references found. Showing first 5:*

- Line 9: `- DETECTOR=none|haar|tflite|ssd   (domyślnie none), vision.detections + vision.person`
- Line 19: `DETECTOR=none|haar|tflite|ssd`
- Line 24: `TFLITE_MODEL=models/efficientdet_lite0.tflite`
- Line 61: `TFLITE_MODEL = os.getenv("TFLITE_MODEL", "models/efficientdet_lite0.tflite").strip()`
- Line 74: `# ── OpenCV`

#### `apps/camera/preview_lcd_hybrid.py`

*34 references found. Showing first 5:*

- Line 5: `# PoC: SSD do inicjalizacji, tracker do podtrzymania, opcjonalny HAAR w ROI.`
- Line 6: `# Publikuje vision.person (tracker/SSD) i vision.face (HAAR).`
- Line 11: `import cv2`
- Line 40: `90: cv2.ROTATE_90_CLOCKWISE,`
- Line 41: `180: cv2.ROTATE_180,`

#### `apps/camera/preview_lcd_ssd.py`

*29 references found. Showing first 5:*

- Line 6: `# Preview + MobileNet-SSD (Caffe) — zapis RAW/PROC do /home/pi/robot/snapshots (atomowo)`
- Line 7: `# + ramki na LCD, + heartbeat, + publikacja vision.person (tylko przy realnym trafieniu)`
- Line 11: `import cv2`
- Line 19: `HB = CameraHB(mode="ssd")`
- Line 78: `k = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}[rot]`

#### `apps/camera/preview_lcd_takeover.py`

- Line 8: `import cv2`
- Line 51: `img = cv2.resize(img_bgr, (320, 240), interpolation=cv2.INTER_LINEAR)`
- Line 52: `img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)`
- Line 92: `Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)).save(tmp, "JPEG", quality=80)`

#### `apps/camera/ssd_preview_writer.py`

*21 references found. Showing first 5:*

- Line 4: `# SSD preview + pewny zapis RAW/PROC do /home/pi/robot/snapshots (atomowo) + LCD`
- Line 8: `import cv2`
- Line 48: `k = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}[ROT]`
- Line 49: `frame = cv2.rotate(frame, k)`
- Line 51: `frame = cv2.flip(frame, 1)`

#### `apps/camera/utils.py`

- Line 9: `import cv2`
- Line 31: `return True, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)`
- Line 35: `cap = cv2.VideoCapture(0)`
- Line 36: `cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])`
- Line 37: `cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])`
- Line 39: `cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))`

#### `apps/ui/manager.py`

- Line 20: `VISION_T = os.getenv("VISION_TOPIC", "vision.state").encode()`

#### `apps/ui/overlay.py`

- Line 16: `VISION_T = os.getenv("VISION_TOPIC", "vision.state").encode()`
- Line 39: `state = {"motion": {}, "vision": {}}`
- Line 58: `state["vision"] = json.loads(payload.decode("utf-8"))`
- Line 64: `v = state.get("vision", {})`
- Line 70: `f"VISION: moving={v.get('moving')} human={v.get('human', False)} motion={v.get('motion', 0):.1f}"`

#### `apps/vision/detector_hog.py`

*18 references found. Showing first 5:*

- Line 4: `# apps/vision/detector_hog.py`
- Line 8: `import cv2`
- Line 16: `HB = CameraHB(mode="hog")`
- Line 36: `return True, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)`
- Line 40: `cap = cv2.VideoCapture(0)`

#### `apps/vision/detector_tflite.py`

- Line 4: `# apps/vision/dispatcher.py`
- Line 6: `Zbiera zdarzenia z detektorów (HAAR/SSD/itd.), normalizuje je,`
- Line 8: `Topics IN:  vision.face, vision.person, vision.detections`
- Line 9: `Topics OUT: vision.state, autonomy.perception (opcjonalnie), ui.face (opcjonalnie)`
- Line 79: `Sprowadzamy HAAR/SSD/hybrid do:`
- Line 117: `pub("vision.state", payload)`
- Line 127: `if not topic.startswith("vision."):`
- Line 144: `pub("vision.dispatcher.heartbeat", {"ts": time.time(), "present": STATE.present})`
- Line 153: `print("[dispatcher] starting (topics: vision.face/person/detections)", flush=True)`
- Line 155: `SUB = zmq_sub(["vision.face", "vision.person", "vision.detections"])`

#### `apps/vision/dispatcher.py`

*15 references found. Showing first 5:*

- Line 4: `# apps/vision/dispatcher.py`
- Line 6: `Zbiera zdarzenia z detektorów (HAAR/SSD/itd.), normalizuje je,`
- Line 8: `IN : vision.face, vision.person, vision.detections`
- Line 9: `OUT: vision.state, vision.dispatcher.heartbeat`
- Line 134: `Sprowadzamy HAAR/SSD/hybrid do:`

#### `apps/vision/edge_preview.py`

*17 references found. Showing first 5:*

- Line 8: `import cv2`
- Line 28: `img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)`
- Line 30: `img = cv2.rotate(img, cv2.ROTATE_180)`
- Line 32: `img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)`
- Line 34: `img = cv2.flip(img, 1)`

#### `apps/vision/obstacle_roi.py`

*16 references found. Showing first 5:*

- Line 23: `import cv2  # type: ignore`
- Line 110: `return cv2.imread(path, cv2.IMREAD_GRAYSCALE)`
- Line 125: `nz = cv2.countNonZero(roi)`
- Line 134: `lap = cv2.Laplacian(roi, cv2.CV_64F)`
- Line 155: `return cv2.cvtColor(img_gray, cv2.COLOR_GRAY2BGR)`


### common/

#### `common/cam_heartbeat.py`

- Line 13: `hb = CameraHB(mode="haar")  # albo "ssd"/"hybrid"`

#### `common/snap.py`

- Line 23: `import cv2`
- Line 76: `cv2.imwrite(path, bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])`
- Line 90: `"""Zapis obrazu po obróbce (np. SSD/HAAR/hybrid)."""`
- Line 112: `bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)`


### config/

#### `config/alsa/preflight.sh`

- Line 123: `log_warn "lsof not found - cannot detect blocking processes"`


### scripts/

#### `scripts/dev_bus-dump.py`

- Line 18: `TOPIC="vision" python3 scripts/dev_bus-dump.py  # dump 'vision'`

#### `scripts/dev_bus-pub.py`

- Line 15: `python3 scripts/dev_bus-pub.py vision.state '{"moving": false, "human": true}'`

#### `scripts/diag_bench-detect.sh`

- Line 2: `# scripts/diag_bench-detect.sh DUR`
- Line 48: `# 2) SSD`
- Line 50: `fps="$(run_and_parse_fps "SSD" python3 -u apps/camera/preview_lcd_ssd.py)" || exit 1`
- Line 51: `num_ge "$fps" "$MIN_SSD" || { log "FAIL: SSD < $MIN_SSD"; exit 1; }`
- Line 59: `log "PASS: all >= thresholds (HAAR>=$MIN_HAAR, SSD>=$MIN_SSD, HYBRID>=$MIN_HYB)"`

#### `scripts/diag_bus-spy.py`

- Line 13: `for t in ("cmd.", "motion.", "vision."):`

#### `scripts/diagnose_services.sh`

- Line 13: `NAMES_ORDER=(broker web motion cam edge ssd obstacle api)  # api NA KOŃCU i TYLKO STATUS!`

#### `scripts/sys_control.sh`

- Line 9: `rider-vision.service`
- Line 13: `rider-ssd-preview.service`

#### `scripts/sys_vision-control.sh`

- Line 2: `# Rider-Pi Vision Control Script`
- Line 3: `# Zarządzanie usługą vision: on/off/burst/status`
- Line 7: `SERVICE="rider-vision.service"`
- Line 13: `echo "[vision] starting $SERVICE"`
- Line 18: `echo "[vision] stopping $SERVICE"`
- Line 23: `echo "[vision] burst mode: running $SERVICE for ${secs}s"`
- Line 28: `echo "[vision] burst finished → stopping $SERVICE"`

#### `scripts/systemd-sync.sh`

- Line 18: `"rider-vision.service"`
- Line 25: `"rider-ssd-preview.service"   # linkujemy, bez enable — start wg Wants/ lub ręcznie`

#### `scripts/util_load-config.sh`

- Line 15: `# Detect project root`


### services/

#### `services/api_core/camera.py`

- Line 120: `Brak podglądu (vision wyłączone)`

#### `services/api_core/compat.py`

- Line 488: `vision = {`
- Line 502: `out = {"bus": bus, "vision": vision, "xgo": xgo, "flags": flags}`

#### `services/api_core/device_status.py`

- Line 53: `"vision": {"running": None, "last_frame": get_last_frame_info()},`

#### `services/api_core/devices.py`

- Line 94: `for t in ("vision.", "camera.", "motion.bridge.", "motion.", "cmd.", "devices.", "xgo."):`
- Line 114: `if topic == "vision.dispatcher.heartbeat":`
- Line 204: `if topic == "vision.state":`

#### `services/api_core/services_api.py`

- Line 30: `"ssd": "rider-ssd-preview.service",`
- Line 34: `"last": "rider-ssd-preview.service",`
- Line 35: `"lastframe": "rider-ssd-preview.service",`
- Line 43: `"rider-ssd-preview.service",`

#### `services/api_core/state_api.py`

- Line 67: `"""Deleguje do state() i dokleja vision.obstacle (jeśli dostępne)."""`
- Line 83: `payload.setdefault("vision", {})["obstacle"] = obst`

#### `services/api_core/vision_api.py`

- Line 39: `return os.getenv("SSD_PATH", os.path.join(C.SNAP_DIR, "ssd.jpg"))`
- Line 57: `@bp.route("/vision/cam", methods=["GET", "HEAD"])`
- Line 62: `@bp.route("/vision/edge", methods=["GET", "HEAD"])`
- Line 67: `@bp.route("/vision/ssd", methods=["GET", "HEAD"])`
- Line 75: `@bp.route("/vision/snap-info", methods=["GET", "HEAD"])`
- Line 97: `"ssd": info(_ssd_path()),`
- Line 138: `@bp.route("/vision/obstacle", methods=["GET", "HEAD"])`

#### `services/api_server.py`

- Line 518: `app.register_blueprint(_bp)  # /vision/*`
- Line 519: `app.register_blueprint(_bp, url_prefix="/api")  # /api/vision/*`
- Line 520: `app.logger.info("[api] vision_api blueprints registered: /vision/* and /api/vision/*")`


### tests/

#### `tests/test_vad_state_reset.py`

- Line 17: `assert result is True, "Window should be full and detect end of speech"`
- Line 24: `# After reset, should not immediately detect end of speech`
- Line 26: `assert result is False, "Should not detect end of speech immediately after reset"`
- Line 61: `assert vad.tail.push(False) is True, "Should detect end of speech after silence frames"`
- Line 63: `# Without reset, subsequent calls would immediately detect end of speech`
- Line 83: `assert immediate_result is False, "Should not immediately detect end after reset"`

#### `tests/test_vision_dispatcher.py`

- Line 13: `disp = importlib.import_module("apps.vision.dispatcher")`
- Line 34: `evt = disp.normalize_event("vision.person", {"present": True, "score": 0.8})`
- Line 38: `# 2) drugi pozytyw — powinniśmy wejść w present=True i mieć vision.state`
- Line 41: `assert any(t == "vision.state" and p.get("present") is True for t, p in published)`
- Line 47: `assert any(t == "vision.state" and p.get("present") is False for t, p in published)`


---

## Camera Integration

**Files with Camera Integration references**: 120

### apps/

#### `apps/camera/__main__.py`

- Line 8: `from apps.camera.preview_lcd_takeover import main as preview_main`
- Line 18: `p = argparse.ArgumentParser(description="Rider-Pi camera preview launcher")`
- Line 22: `p.add_argument("--skip-v4l2", action="store_true", help="pomin V4L2, wymusz Picamera2")`
- Line 23: `p.add_argument("--warmup", type=int, help="rozgrzewka klatek (Picamera2)")`

#### `apps/camera/cam_motion.py`

- Line 2: `ŚCIEŻKA: apps/camera/cam_motion.py`
- Line 26: `python3 -m apps.camera.cam_motion`
- Line 27: `VISION_HUMAN=1 VISION_FACE_EVERY=5 python3 -m apps.camera.cam_motion`
- Line 63: `import cv2  # type: ignore`
- Line 163: `ok, frame = cap.read()`
- Line 168: `frame = cv2.resize(frame, (LORES_W, LORES_H))`
- Line 169: `prev_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)`
- Line 181: `gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)`
- Line 222: `if __name__ == "__main__" or __name__ == "apps.camera.cam_motion":`

#### `apps/camera/preview_lcd.py`

*18 references found. Showing first 5:*

- Line 7: `- Publikuje heartbeat na busie:   camera.heartbeat`
- Line 10: `- Picamera2→V4L2 fallback`
- Line 43: `from PIL import Image  # PIL używany do LCD`
- Line 45: `from apps.camera.utils import open_camera`
- Line 76: `import cv2`

#### `apps/camera/preview_lcd_hybrid.py`

*16 references found. Showing first 5:*

- Line 4: `# apps/camera/preview_lcd_hybrid.py`
- Line 7: `# + wysyła camera.heartbeat + snapshoty RAW/proc/LCD/LCD_fb`
- Line 11: `import cv2`
- Line 14: `from apps.camera.utils import env_flag, open_camera`
- Line 37: `def apply_rotation(frame, rot: int, flip_h: bool, flip_v: bool):`

#### `apps/camera/preview_lcd_ssd.py`

*18 references found. Showing first 5:*

- Line 2: `# apps/camera/preview_lcd_ssd.py`
- Line 11: `import cv2`
- Line 13: `from apps.camera.utils import env_flag, open_camera`
- Line 76: `def apply_rotation(frame, rot, flip_h, flip_v):`
- Line 79: `frame = cv2.rotate(frame, k)`

#### `apps/camera/preview_lcd_takeover.py`

- Line 4: `# apps/camera/preview_lcd_takeover.py`
- Line 8: `import cv2`
- Line 10: `from PIL import Image`
- Line 12: `from apps.camera.utils import open_camera`
- Line 53: `_LCD.ShowImage(Image.fromarray(img_rgb))`
- Line 56: `# --- Camera ---`
- Line 73: `ok, frame = read()`
- Line 84: `out = frame.copy()`
- Line 92: `Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)).save(tmp, "JPEG", quality=80)`
- Line 95: `print(f"[save-frame] error: {e}", flush=True)`

#### `apps/camera/ssd_preview_writer.py`

*16 references found. Showing first 5:*

- Line 8: `import cv2`
- Line 10: `from apps.camera.utils import env_flag, open_camera`
- Line 46: `def apply_rotation(frame):`
- Line 49: `frame = cv2.rotate(frame, k)`
- Line 51: `frame = cv2.flip(frame, 1)`

#### `apps/camera/utils.py`

- Line 1: `"""Shared helpers for camera preview scripts."""`
- Line 9: `import cv2`
- Line 20: `"""Open Picamera2 when available, falling back to V4L2."""`
- Line 22: `from picamera2 import Picamera2  # type: ignore`
- Line 24: `picam2 = Picamera2()`

#### `apps/google_bridge/puller.py`

- Line 49: `def signal_handler(signum: int, frame: Any) -> None:`

#### `apps/hw/sink_lcd.py`

*13 references found. Showing first 5:*

- Line 5: `Dwie ścieżki: RAW (push_rgb565) i fallback (show_image PIL.Image).`
- Line 11: `from PIL import Image  # noqa: E402`
- Line 40: `def push_auto(self, img: Image.Image):`
- Line 49: `def _apply_rotation(self, img: Image.Image) -> Image.Image:`
- Line 55: `def pil_to_rgb565(img: Image.Image) -> bytes:`

#### `apps/ui/face/__main__.py`

- Line 12: `from PIL import Image, ImageDraw`
- Line 49: `im = Image.open(BytesIO(png)).convert("RGB").rotate(deg, expand=True)`
- Line 59: `def img_to_rgb565(img: Image.Image) -> bytes:`
- Line 181: `png = fc.frame()`
- Line 182: `face = Image.open(BytesIO(png)).convert("RGB")`
- Line 185: `canvas = Image.new("RGB", (fb_w, fb_h), (20, 0, 40) if debug else (8, 36, 70))`

#### `apps/ui/face/controller.py`

- Line 10: `from PIL import Image`
- Line 248: `def frame(self) -> bytes:`
- Line 255: `def frame_image(self) -> Image.Image:`
- Line 256: `"""Zwraca PIL.Image (używane przez scripts/dev_face-lcd-direct.py)."""`
- Line 258: `data = self.frame()`
- Line 259: `return Image.open(BytesIO(data)).convert("RGB")`
- Line 269: `img = Image.new("RGB", (self.size, self.size), (30, 58, 138))`
- Line 280: `yield self.frame()`

#### `apps/ui/face/driver/mock.py`

- Line 6: `from PIL import Image`
- Line 14: `def push_png(self, img: Image.Image):`
- Line 32: `img = Image.fromarray(rgb, "RGB")`

#### `apps/ui/face/face_io.py`

- Line 6: `from PIL import Image`
- Line 9: `def to_rgb565(img: Image.Image) -> bytes:`
- Line 18: `def apply_rotate(img: Image.Image, deg: int) -> Image.Image:`
- Line 24: `def fit_strategy(img: Image.Image, mode: Literal["fill", "fit", "stretch"], size=(240, 240)) -> Imag...`
- Line 30: `bg = Image.new("RGB", size, (0, 0, 0))`

#### `apps/ui/face/renderer.py`

- Line 11: `from PIL import Image, ImageDraw  # noqa: E402`
- Line 29: `img = Image.new("RGB", (self.size, self.size), (30, 58, 138))`

#### `apps/ui/manager.py`

- Line 13: `from PIL import Image`
- Line 15: `Image = None`
- Line 144: `if XGO_BLACK and Image and self._xgo_size:`
- Line 146: `from PIL import Image as _I`
- Line 171: `if not on and Image and self._xgo_size:`

#### `apps/vision/detector_hog.py`

- Line 8: `import cv2`
- Line 10: `from PIL import Image`
- Line 27: `from picamera2 import Picamera2`
- Line 29: `picam2 = Picamera2()`
- Line 52: `Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).save(tmp, "JPEG", quality=80)`
- Line 69: `ok, frame = read()`
- Line 75: `rects, weights = hog.detectMultiScale(frame, winStride=(8, 8), padding=(8, 8), scale=1.05)`
- Line 76: `out = frame.copy()`

#### `apps/vision/dispatcher.py`

- Line 67: `Odbiór z SUB — wspiera single-frame ("topic payload") i multipart.`

#### `apps/vision/edge_preview.py`

*13 references found. Showing first 5:*

- Line 8: `import cv2`
- Line 49: `# --- Backend A: Picamera2/libcamera ---`
- Line 53: `from picamera2 import Picamera2`
- Line 55: `picam = Picamera2()`
- Line 84: `print("[edge] ERROR: cannot open camera(0) via V4L2", flush=True)`

#### `apps/vision/obstacle_roi.py`

- Line 23: `import cv2  # type: ignore`

#### `apps/voice/audio/__init__.py`

- Line 2: `"""Audio package for Rider-Pi voice (ALSA helpers, capture/playback, errors)."""`

#### `apps/voice/audio/alsa.py`

- Line 108: `"""Test if device can be opened for capture/playback."""`
- Line 109: `if mode == "capture":`
- Line 166: `logger.event("alsa.ensure_free.start", capture=capture_resolved, playback=playback_resolved, force=f...`
- Line 169: `result["capture_free"] = _test_device_access(capture_resolved, "capture")`
- Line 188: `result["errors"].append(f"Capture device {capture_resolved} is not accessible")`

#### `apps/voice/audio/capture.py`

*13 references found. Showing first 5:*

- Line 1: `# apps/voice/audio/capture.py`
- Line 101: `for frame in cap.frames():`
- Line 130: `self.logger = logger or voice_logging.get_logger("voice.capture")`
- Line 190: `raise CaptureError(f"Failed to start capture command: {exc}") from exc`
- Line 191: `self.logger.event("capture.proc.start", command=" ".join(cmd))`

#### `apps/voice/cli.py`

- Line 173: `if getattr(args, "capture", None):`
- Line 174: `overrides = _merge(overrides, voice_config.override_from_pairs("capture", args.capture))`

#### `apps/voice/cli_commands.py`

- Line 48: `listen.add_argument("--capture", nargs="*")`
- Line 64: `ptt.add_argument("--capture", nargs="*")`
- Line 81: `once.add_argument("--capture", nargs="*")`
- Line 193: `capture_backend = config.get("capture", {}).get("backend", "alsa")`
- Line 194: `print("Capture backend:", capture_backend)`
- Line 294: `for section in ["asr", "chat", "tts", "vad", "turn", "playback", "capture", "service"]:`

#### `apps/voice/config_loader.py`

- Line 48: `- sprawdzać sekcje: 'capture' in ConfigSchema()`
- Line 49: `- pobierać zestawy kluczy: ConfigSchema()['capture']`
- Line 84: `("capture", "rate"): ("capture", "sample_rate"),`
- Line 85: `("capture", "format"): ("capture", "sample_format"),`
- Line 92: `"capture": {"device", "sample_rate", "channels", "sample_format"},`
- Line 403: `cap = data.get("capture", {}) if isinstance(data.get("capture"), dict) else {}`
- Line 405: `self.validation_errors.append("Field 'capture.channels' must be one of [1, 2]")`
- Line 408: `"Field 'capture.sample_rate' must be one of [16000, 22050, 24000, 44100, 48000]"`
- Line 411: `self.validation_errors.append("Field 'capture.sample_format' must be a string (e.g., 'S16_LE')")`

#### `apps/voice/errors.py`

- Line 19: `"""Audio capture/playback related errors."""`
- Line 37: `"""Audio capture errors."""`

#### `apps/voice/kws.py`

*14 references found. Showing first 5:*

- Line 225: `def wait(self, capture: Any, timeout: float | None = None) -> bool:`
- Line 236: `return self._wait_nyumaya(capture, timeout, start)`
- Line 239: `return self._wait_porcupine(capture, timeout, start)`
- Line 246: `def _wait_nyumaya(self, capture: Any, timeout: float | None, start: float) -> bool:`
- Line 248: `read = _make_reader(capture)`

#### `apps/voice/session_prefs.py`

- Line 80: `capture_cfg: Optional capture config object (CaptureConfig)`
- Line 103: `# Input sample rate (from capture config or default)`
- Line 107: `cfg_capture = (config or {}).get("capture", {}) or {}`

#### `apps/voice/stream/playout.py`

- Line 2: `"""Audio capture and TTS playback worker threads for streaming voice service.`
- Line 5: `- Audio capture (microphone → queue)`
- Line 17: `from ..audio.capture import CaptureConfig`
- Line 23: `"""Mixin providing audio capture and TTS playback workers for StreamingVoiceService."""`
- Line 41: `# Audio capture worker`
- Line 44: `"""Start audio capture thread (generator → queue)."""`
- Line 56: `"capture.start",`
- Line 85: `self._capture_thread = threading.Thread(target=capture_target, name="stream-capture", daemon=True)`

#### `apps/voice/stream/svc_streaming.py`

- Line 9: `- StreamPlayoutMixin: Audio capture and TTS playback workers`
- Line 24: `from ..audio.capture import CaptureConfig`
- Line 200: `# Capture configuration for chunk processing`
- Line 201: `capture_in = dict(self.config.get("capture", {}) or {})`
- Line 550: `channels_cfg = int(self.config.get("capture", {}).get("channels", 1))  # type: ignore[attr-defined]`

#### `apps/voice/stream_chunks.py`

- Line 19: `from .audio.capture import CaptureConfig`

#### `apps/voice/svc_audio.py`

*29 references found. Showing first 5:*

- Line 2: `"""Voice service audio I/O adapter - ALSA, capture, playback, ding."""`
- Line 13: `from .audio.capture import AudioCapture, CaptureConfig, CaptureError`
- Line 21: `Wejście: surowe PCM z capture (S16_LE, interleaved kanały).`
- Line 48: `"""Capture audio @16kHz mono; returns bytes for transcribe_file()."""`
- Line 56: `with AudioCapture(capture_cfg, logger) as capture:`

#### `apps/voice/svc_file.py`

*25 references found. Showing first 5:*

- Line 30: `from .audio.capture import AudioCapture, CaptureConfig, CaptureError`
- Line 155: `# CAPTURE — domyślnie ALSA (nie 'dummy')`
- Line 156: `_cap_in = dict(config.get("capture") or {})`
- Line 380: `with AudioCapture(self._capture_cfg, self.logger) as capture:`
- Line 381: `if not self._hotword.wait(capture):`

#### `apps/voice/svc_signals.py`

- Line 16: `def handler(signum, frame):  # pragma: no cover`

#### `apps/voice/vad.py`

- Line 21: `def rms_dbfs(frame: bytes) -> float:`
- Line 26: `if not frame:`
- Line 29: `samples = [int.from_bytes(frame[i : i + 2], "little", signed=True) for i in range(0, len(frame), 2)]`
- Line 90: `def _is_speech_energy(self, frame: bytes) -> bool:`
- Line 92: `return rms_dbfs(frame) >= self.energy_gate`
- Line 94: `def __call__(self, frame: bytes) -> bool:`
- Line 96: `:param frame: bajty S16_LE (mono); przy stereo też zadziała heurystycznie`
- Line 104: `is_speech = self._is_speech_energy(frame)`
- Line 108: `if rms_dbfs(frame) < self.energy_gate:`
- Line 112: `is_speech = self._vad.is_speech(frame, self.sample_rate)`

#### `apps/voice/voice_logging.py`

- Line 44: `# np. obiekty websockets (ClientConnection, Frame) → zamieniamy na str()`


### common/

#### `common/cam_heartbeat.py`

- Line 15: `hb.tick(frame, fps, presenting=True)  # wołaj co klatkę; wyśle co ~1 s`
- Line 29: `def _shape(self, frame) -> tuple[int, int]:`
- Line 31: `h, w = frame.shape[:2]`
- Line 36: `def tick(self, frame, fps: float | None, presenting: bool = True) -> None:`
- Line 40: `h, w = self._shape(frame)`
- Line 42: `"camera.heartbeat",`

#### `common/snap.py`

- Line 23: `import cv2`


### config/

#### `config/alsa/preflight.sh`

*13 references found. Showing first 5:*

- Line 12: `#   config/alsa/preflight.sh [--force] [--capture DEVICE] [--playback DEVICE]`
- Line 16: `#   config/alsa/preflight.sh --capture wm8960_in --playback wm8960_out`
- Line 19: `#   config/alsa/preflight.sh --force --capture wm8960_in`
- Line 68: `--capture DEVICE       Specify capture device to check (e.g., wm8960_in)`
- Line 79: `$0 --capture wm8960_in --playback wm8960_out`

#### `config/alsa/wm8960-mixer.sh`

- Line 8: `amixer -c $card sset 'ADC Capture Switch' on 2>/dev/null || true`
- Line 9: `amixer -c $card sset 'ADC Capture Volume' 160 2>/dev/null || true`

#### `config/voice.toml`

- Line 3: `[capture]`

#### `config/voice_gemini_example.toml`

- Line 6: `[capture]`

#### `config/voice_gemini_file.toml`

- Line 7: `[capture]`

#### `config/voice_local_file.toml`

- Line 1: `[capture]`

#### `config/voice_openai_file.toml`

- Line 7: `[capture]`

#### `config/voice_openai_streaming.toml`

- Line 28: `[capture]`

#### `config/voice_openai_streaming_fallback.toml`

- Line 3: `[capture]`


### drivers/

#### `drivers/lcd/driver_ili9xx.py`

- Line 23: `from PIL import Image`
- Line 25: `Image = None`
- Line 130: `if Image is None:`
- Line 212: `def ShowImage(self, img: Image.Image):`
- Line 219: `img = img.resize((self.width, self.height), Image.BILINEAR)`
- Line 271: `from PIL import Image as _Image`
- Line 277: `"""Powolny fallback: konwersja RGB565 -> PIL.Image (tylko awaryjnie)."""`
- Line 609: `# ==== Rider-Pi: cache CASET/RASET (window) to avoid per-frame overhead =========`

#### `drivers/lcd/mock.py`

- Line 6: `from PIL import Image`
- Line 14: `def push_png(self, img: Image.Image):`
- Line 32: `img = Image.fromarray(rgb, "RGB")`

#### `drivers/lcd/sim.py`

*11 references found. Showing first 5:*

- Line 46: `Simulate pushing a PNG image to the display.`
- Line 49: `img: PIL Image object`
- Line 53: `LOG.debug(f"[SIM] push_png frame={self.frame_count} size={size}")`
- Line 59: `self._write_meta({"mode": "png", "size": list(size), "frame": self.frame_count})`
- Line 61: `LOG.warning(f"[SIM] Failed to save frame: {e}")`


### examples/

#### `examples/demo_driver_factory.py`

- Line 96: `# Try to create a simple image (requires PIL)`
- Line 98: `from PIL import Image, ImageDraw`
- Line 101: `img = Image.new("RGB", (240, 240), color=(0, 0, 128))`
- Line 106: `LOG.info("Displaying image...")`
- Line 111: `LOG.warning("PIL not available - skipping image test")`

#### `examples/demo_sim3_sensors.py`

*12 references found. Showing first 5:*

- Line 5: `This script demonstrates the gyroscope and camera sensors publishing`
- Line 56: `camera = VirtualCamera(width=320, height=240, fov=60.0, rate_hz=5.0)`
- Line 58: `print(f"   ✓ Camera: {CAMERA_TOPIC} @ 5 Hz (320x240, FOV=60°)")`
- Line 74: `print("   Time    | Gyro Angle | Camera | Robot Position")`
- Line 84: `pre_camera_time = camera.last_pub`


### scripts/

#### `scripts/demo/config_validation.py`

- Line 99: `loader.load("voice_openai_file.toml", overrides={"capture": {"channels": 3}})`

#### `scripts/demo/streaming.py`

- Line 96: `"capture": {"backend": "alsa", "sample_rate": 16000},`
- Line 128: `"capture": {"backend": "alsa"},`

#### `scripts/demo_weather-lcd.py`

- Line 25: `from PIL import Image, ImageDraw, ImageFont`
- Line 186: `def render_card(data: dict[str, Any], place_label: str) -> Image.Image:`
- Line 187: `img = Image.new("L", (W, H), color=255)`
- Line 255: `def push_to_lcd(img: Image.Image, rotate: int = 270, spi_hz: int | None = None) -> None:`
- Line 263: `img = img.resize((240, 320), Image.BICUBIC)`
- Line 353: `canvas = Image.new("L", (W, H), 255)`

#### `scripts/dev_check-legacy-imports.py`

- Line 11: `- apps/voice/capture.py (removed in PR-3, use apps.voice.audio.capture)`
- Line 48: `(r"from apps\.voice\.capture\b", "apps/voice/capture.py (removed in PR-3, use apps.voice.audio.captu...`
- Line 50: `(r"import apps\.voice\.capture\b", "apps/voice/capture.py (removed in PR-3, use apps.voice.audio.cap...`

#### `scripts/dev_face-cli.py`

- Line 8: `from PIL import Image, ImageDraw`
- Line 29: `def make_expr_img(expr: str) -> Image.Image:`
- Line 31: `img = Image.new("RGB", PANEL_SIZE, color)`

#### `scripts/dev_face-lcd-clean.py`

- Line 110: `data = fc.frame()`
- Line 111: `from PIL import Image`
- Line 113: `img = Image.open(BytesIO(data)).convert("RGB")`
- Line 119: `from PIL import Image, ImageDraw`
- Line 122: `img = Image.new("RGB", (W, H), (0, 0, 64))`
- Line 202: `im0 = Image.open(args.img).convert("RGB")`
- Line 241: `rot_map = {90: Image.ROTATE_90, 180: Image.ROTATE_180, 270: Image.ROTATE_270}`
- Line 248: `img = img.resize((W, H), Image.BILINEAR)`

#### `scripts/dev_face-lcd-direct.py`

*13 references found. Showing first 5:*

- Line 17: `from PIL import Image`
- Line 40: `r"(img|image|frame|png|rgb|buf|buffer|disp|show|blit|push|draw|render|present|send|write|update|put)...`
- Line 46: `def to_png_bytes(img: Image.Image) -> bytes:`
- Line 68: `def to_rgb565_bytes(img: Image.Image) -> bytes:`
- Line 249: `def _prep(self, img: Image.Image) -> Image.Image:`

#### `scripts/dev_face-presenter.py`

- Line 11: `from PIL import Image, ImageDraw`
- Line 57: `img = Image.new("RGB", (w, h), "white")`

#### `scripts/dev_lcd-clear.py`

- Line 8: `from PIL import Image`
- Line 78: `img = Image.new("RGB", (W, H), "black")`

#### `scripts/dev_lcd-show-raw.py`

- Line 9: `from PIL import Image, ImageDraw`
- Line 55: `src = Image.open(p).convert("RGB")`
- Line 58: `src = Image.new("RGB", (W, H))`
- Line 79: `src = src.resize((W, H), Image.BILINEAR)`
- Line 95: `print(f"[ok] RAW image pushed: {W}x{H}, SPI_HZ={SPI_HZ}, MODE={SPI_MODE}, MADCTL=0x{MADCTL:02X}, COL...`

#### `scripts/dev_lcd-testcard.py`

- Line 8: `from PIL import Image, ImageDraw`
- Line 69: `img = Image.new("RGB", (W, H), "white")`

#### `scripts/diag_bench-detect.sh`

- Line 44: `fps="$(run_and_parse_fps "HAAR" python3 -u apps/camera/preview_lcd_takeover.py)" || exit 1`
- Line 50: `fps="$(run_and_parse_fps "SSD" python3 -u apps/camera/preview_lcd_ssd.py)" || exit 1`
- Line 56: `fps="$(run_and_parse_fps "HYBRID" python3 -u apps/camera/preview_lcd_hybrid.py)" || exit 1`

#### `scripts/diag_framebuffer-grab.py`

- Line 28: `from PIL import Image`
- Line 31: `def fb_to_image(dev: str, w: int, h: int, fmt: str = "RGB565") -> Image.Image:`
- Line 51: `return Image.fromarray(rgb, mode="RGB")`
- Line 59: `img = img.transpose(Image.ROTATE_270)  # cw 90`
- Line 61: `img = img.transpose(Image.ROTATE_180)`
- Line 63: `img = img.transpose(Image.ROTATE_90)  # cw 270`

#### `scripts/sim/run_simulation.py`

- Line 57: `camera = VirtualCamera(width=320, height=240, fov=60.0, rate_hz=5.0)`
- Line 80: `# Render camera view`
- Line 81: `camera_surface = camera.render(robot.x, robot.y, robot.angle, world.wall_segments)`
- Line 82: `camera.publish()`

#### `scripts/sys_camera-kill.sh`

- Line 2: `# camera_takeover_kill.sh — free camera/SPI and light up LCD backlight`
- Line 21: `pkill -f 'apps/camera/preview_lcd_takeover.py' || true`
- Line 22: `pkill -f 'apps/camera/preview_lcd_ssd.py' || true`
- Line 23: `pkill -f 'apps/camera/preview_lcd_hybrid.py' || true`

#### `scripts/sys_camera-preview.sh`

- Line 14: `CMD=(sudo -E python3 -m apps.camera --rot "$PREVIEW_ROT" --warmup "$PREVIEW_WARMUP")`

#### `scripts/sys_kill-cam.sh`

- Line 3: `pkill -f 'apps/camera/preview_.*\.py' 2>/dev/null || true`
- Line 4: `pkill -f 'apps/camera/ssd_.*\.py' 2>/dev/null || true`

#### `scripts/sys_splash-info.py`

*14 references found. Showing first 5:*

- Line 16: `from PIL import Image, ImageDraw, ImageFont`
- Line 145: `def _letterbox_fit(im: Image.Image, target_wh: tuple[int, int]) -> Image.Image:`
- Line 153: `im2 = im.resize((nw, nh), Image.LANCZOS)`
- Line 154: `canvas = Image.new("RGB", (tw, th), (0, 0, 0))`
- Line 486: `def draw_splash_with(info: dict, w: int, h: int) -> Image.Image:`

#### `scripts/sys_splash-info.sh`

- Line 42: `from PIL import Image`
- Line 59: `im = Image.open(logo_path).convert("RGB")`

#### `scripts/sys_vendor-splash.py`

- Line 7: `from PIL import Image, ImageDraw, ImageFont`
- Line 23: `img = Image.new("RGB", (W, H), (15, 21, 46))`

#### `scripts/sys_voice-once.sh`

- Line 34: `--capture sample_rate=16000 channels=1 \`

#### `scripts/sys_voice-run.sh`

- Line 86: `echo "  VAD: mode=${VAD_MODE} frame=${VAD_FRAME_MS}ms tail=${VAD_SILENCE_TAIL_MS}ms max=${VAD_MAX_LE...`


### services/

#### `services/api_core/camera.py`

- Line 2: `# server/api_core/camera.py`
- Line 17: `".jpg": "image/jpeg",`
- Line 18: `".jpeg": "image/jpeg",`
- Line 19: `".png": "image/png",`
- Line 20: `".bmp": "image/bmp",`
- Line 124: `/camera/raw i /camera/proc zwrócą 404 gdy klatka jest przeterminowana`
- Line 129: `resp.headers["Content-Type"] = "image/svg+xml"`

#### `services/api_core/compat.py`

- Line 231: `"camera": {`
- Line 511: `# ale realny plik to snapshots/raw.jpg — aplikacje i tak korzystały z /camera/last.`

#### `services/api_core/devices.py`

- Line 94: `for t in ("vision.", "camera.", "motion.bridge.", "motion.", "cmd.", "devices.", "xgo."):`
- Line 216: `if topic == "camera.heartbeat":`

#### `services/api_core/face_anim.py`

- Line 12: `from PIL import Image`
- Line 34: `def present(self, img: Image.Image) -> None:`
- Line 152: `# Fallback: dekoduj PNG -> PIL.Image i przekaż`
- Line 153: `img = Image.open(BytesIO(png)).convert("RGB")`

#### `services/api_core/face_api.py`

- Line 30: `Dla ścieżki plikowej działają aliasy: file/image/png.`
- Line 33: `if b in {"file", "image"}:`
- Line 89: `# Fallback: FaceController → frame() / frame_image()`
- Line 93: `from PIL import Image`
- Line 102: `buf = BytesIO(fc.frame())`
- Line 103: `img = Image.open(buf).convert("RGB")`
- Line 125: `img = Image.open(BytesIO(png)).convert("RGB")`
- Line 137: `"""Wyrenderuj jedną klatkę jako PIL.Image (bezpośrednio, nie PNG)."""`
- Line 144: `return r.render_image(state=state)  # PIL.Image`
- Line 158: `return Image.open(buf).convert("RGB")`

#### `services/api_core/services_api.py`

- Line 26: `# camera pipelines (preview)`
- Line 28: `"camera": "rider-cam-preview.service",  # legacy alias`

#### `services/api_core/state_api.py`

- Line 38: `"camera": {`
- Line 42: `"preview_url": f"/camera/last?t={cache_bust}",`
- Line 43: `"placeholder_url": "/camera/placeholder",`

#### `services/api_core/vision_api.py`

- Line 53: `resp = send_file(path, mimetype="image/jpeg", conditional=True)`

#### `services/api_core/voice_proxy.py`

- Line 45: `"""Proxy /api/voice/capture."""`
- Line 55: `body, code = _forward("/capture", {"sec": sec_f}, None)`

#### `services/api_server.py`

- Line 26: `import services.api_core.camera as camera`
- Line 127: `# camera & snapshots`
- Line 128: `_add_rule("/camera/raw", view_func=camera.camera_raw, methods=["GET", "HEAD"])`
- Line 129: `_add_rule("/camera/proc", view_func=camera.camera_proc, methods=["GET", "HEAD"])`
- Line 130: `_add_rule("/camera/last", view_func=camera.camera_last, methods=["GET", "HEAD"])`
- Line 131: `_add_rule("/camera/placeholder", view_func=camera.camera_placeholder, methods=["GET", "HEAD"])`
- Line 132: `_add_rule("/snapshots/<path:fname>", view_func=camera.snapshots_static)`
- Line 136: `return camera.camera_last()`
- Line 162: `_add_rule("/api/voice/capture", view_func=voice_proxy.capture_handler, methods=["POST", "OPTIONS"])`

#### `services/last_frame_sink.py`

- Line 18: `# Opcjonalny ZMQ heartbeat (camera.heartbeat)`
- Line 40: `_pub.send_string(f"camera.heartbeat {json.dumps(payload)}")`


### sim/

#### `sim/sensors.py`

*11 references found. Showing first 5:*

- Line 3: `Virtual Sensors - Simulated gyroscope and camera with MQTT publishing`
- Line 23: `CAMERA_TOPIC = os.getenv("CAMERA_TOPIC", "rider.camera.frame")`
- Line 67: `"""Virtual camera that renders first-person view with perspective."""`
- Line 81: `# Create camera surface`
- Line 91: `LOG.info(f"Camera PUB → {BUS_PUB_ADDR} topic='{CAMERA_TOPIC}' @ {self.rate_hz} Hz")`

#### `sim/world.py`

- Line 235: `"""Render the side panel with camera view and telemetry."""`
- Line 249: `# Camera view`
- Line 255: `# Scale camera surface to fit panel`
- Line 318: `Advance simulation by one frame.`


### tests/

#### `tests/acceptance_criteria.py`

*12 references found. Showing first 5:*

- Line 56: `camera = VirtualCamera()`
- Line 57: `camera_surface = camera.render(robot.x, robot.y, robot.angle, world.wall_segments)`
- Line 93: `camera = VirtualCamera(width=320, height=240, fov=60.0)`
- Line 101: `surface = camera.render(5.0, 5.0, 0.0, walls)`
- Line 103: `assert surface is not None, "Camera should render a surface"`

#### `tests/config/test_config_loader.py`

*12 references found. Showing first 5:*

- Line 40: `assert "capture" in config`
- Line 47: `assert config["capture"]["device"] == "wm8960_in"`
- Line 48: `assert config["capture"]["sample_rate"] == 16000`
- Line 111: `loader.load("voice_openai_file.toml", overrides={"capture": {"channels": 3}})`
- Line 120: `"capture": {"sample_rate": 8000}  # Not in allowed list`

#### `tests/final_verification_sim3.py`

*20 references found. Showing first 5:*

- Line 50: `# Test 2: Virtual Camera Class`
- Line 54: `camera = VirtualCamera(width=320, height=240, fov=60.0, rate_hz=5.0)`
- Line 55: `assert camera.width == 320`
- Line 56: `assert camera.height == 240`
- Line 57: `assert camera.fov == 60.0`

#### `tests/screenshot_simulator.py`

- Line 38: `# Create camera`
- Line 39: `camera = VirtualCamera(width=320, height=240)`
- Line 44: `camera_surface = camera.render(robot.x, robot.y, robot.angle, world.wall_segments)`
- Line 51: `pygame.image.save(world.screen, "sim_screenshot.png")`

#### `tests/test_blink_shift_coupling.py`

- Line 5: `from PIL import Image`
- Line 11: `img: Image.Image,`

#### `tests/test_camera_api.py`

- Line 12: `"Skipping camera API tests by default (set ALLOW_CAMERA_API_TESTS=1 to enable).",`
- Line 39: `if "camera" not in j:`
- Line 40: `pytest.xfail("`/state` does not expose a 'camera' block on this build.")`
- Line 41: `cam = j["camera"]`
- Line 48: `assert path.endswith("/camera/last")`
- Line 54: `r = c.get("/camera/placeholder")`
- Line 57: `assert ct.startswith("image/svg")  # np. image/svg+xml; charset=utf-8`
- Line 68: `r = c.get("/camera/last")`

#### `tests/test_face_lcd_anim.py`

- Line 43: `r = requests.post(f"{API}/face/render", json={"expr": "happy"}, headers={"Accept": "image/png"})`
- Line 46: `if ct.startswith("image/png"):`
- Line 52: `r2 = requests.post(f"{API}/draw/face", json={"expr": "happy"}, headers={"Accept": "image/png"})`
- Line 55: `if ct2.startswith("image/png"):`

#### `tests/test_face_render_pupil.py`

- Line 7: `from PIL import Image`
- Line 14: `def get_pupil_bbox(img: Image.Image):`
- Line 25: `img_bytes = fc.frame()`
- Line 26: `img = Image.open(BytesIO(img_bytes)).convert("RGB")`

#### `tests/test_face_render_rotation.py`

- Line 7: `from PIL import Image`
- Line 14: `def get_pupil_bbox(img: Image.Image):`
- Line 26: `img_bytes = fc.frame()`
- Line 27: `img0 = Image.open(BytesIO(img_bytes)).convert("RGB")`

#### `tests/test_look_moves_pupil.py`

- Line 5: `from PIL import Image`
- Line 11: `img: Image.Image,`

#### `tests/test_pupil_clamp_and_blink.py`

- Line 5: `from PIL import Image`
- Line 10: `def _eye_rects(img: Image.Image) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:`
- Line 22: `img: Image.Image,`

#### `tests/test_pupil_drift.py`

- Line 5: `from PIL import Image`
- Line 11: `def _pupil_centers(img: Image.Image):`

#### `tests/test_renderer_basics.py`

- Line 2: `from PIL import Image`
- Line 16: `assert isinstance(img, Image.Image)`

#### `tests/test_session_prefs.py`

- Line 19: `"capture": {},`
- Line 70: `"capture": {"sample_rate": 48000},`

#### `tests/test_sim3_acceptance.py`

*32 references found. Showing first 5:*

- Line 3: `Test SIM-3 Acceptance Criteria: Virtual Camera and Gyroscope`
- Line 7: `2. Camera renders first-person view with perspective`
- Line 8: `3. Camera view displayed in side panel`
- Line 9: `4. Camera publishes frames on rider.camera.frame`
- Line 56: `"""AC2: Camera generates first-person view with perspective scaling."""`

#### `tests/test_sim_screenshot.py`

- Line 25: `# Render a frame`
- Line 52: `pygame.image.save(world.screen, "sim_basic_screenshot.png")`

#### `tests/test_simulator_init.py`

- Line 37: `print("✓ Camera initialized")`

#### `tests/test_sink_lcd_path.py`

- Line 6: `from PIL import Image`
- Line 19: `def push_pil(self, image):`
- Line 34: `img = Image.new("RGB", (1, 1))`

#### `tests/test_stream_chunks.py`

- Line 6: `from apps.voice.audio.capture import CaptureConfig`

#### `tests/test_vad_state_reset.py`

- Line 10: `tail = SilenceTail(frame_ms=20, tail_ms=100)  # 5 frame window`
- Line 25: `result = tail.push(False)  # First silence frame after reset`
- Line 34: `# Create a dummy frame (all zeros = silence, very low energy)`

#### `tests/test_voice_audio_normalize.py`

- Line 5: `from apps.voice.audio.capture import CaptureConfig`

#### `tests/test_voice_device_config.py`

- Line 13: `from apps.voice.audio.capture import AudioCapture, CaptureConfig`
- Line 21: `"""Verify capture config accepts and stores device names."""`
- Line 55: `"""Verify capture logs device information when initialized."""`
- Line 60: `with patch("apps.voice.audio.capture.AudioCapture._start_proc") as mock_start:`
- Line 65: `capture = AudioCapture(cfg)`
- Line 66: `with capture:`

#### `tests/test_voice_errors.py`

- Line 58: `error = CaptureError("capture error")`

#### `tests/test_voice_integration.py`

- Line 64: `"capture": {"backend": "alsa"},`

#### `tests/test_voice_service_ui_state.py`

- Line 69: `"capture": {`

#### `tests/test_voice_stream_ptt_defaults.py`

- Line 17: `"capture": {"sample_rate": 16000, "channels": 1},`

#### `tests/test_voice_stream_smoke.py`

- Line 53: `"capture": {"device": "wm8960_in", "sample_rate": 16000, "channels": 2},`
- Line 157: `"capture": {"sample_rate": 16000, "channels": 2},`
- Line 177: `# Mock the logger to capture events`

#### `tests/test_voice_streaming.py`

- Line 89: `"capture": {"backend": "alsa", "sample_rate": 16000, "channels": 1},`
- Line 267: `# Simulate the behavior that would happen in the audio capture thread`

#### `tests/test_voice_svc_stream_proxy.py`

- Line 76: `"capture": {"sample_rate": 16000, "channels": 1},`

#### `tests/test_voice_ws_close.py`

- Line 28: `"capture": {"sample_rate": 16000, "channels": 2},`

#### `tests/test_web_routes.py`

- Line 8: `- GET /camera/last?t=0 → not a redirect (3xx niedozwolone)`
- Line 82: `"""Test that /camera/last?t=0 does not redirect (3xx)."""`
- Line 86: `r = c.get("/camera/last?t=0")`

#### `tests/verify_simulator.py`

- Line 60: `camera = VirtualCamera(width=160, height=120)`
- Line 62: `# Test camera rendering`
- Line 66: `test_surface = camera.render(5.0, 5.0, 0.0, [])`
- Line 67: `assert test_surface is not None, "Camera should render a surface"`


---

## Audio Hardware

**Files with Audio Hardware references**: 69

### apps/

#### `apps/chat/main.py`

- Line 5: `apps/chat/main.py — Chat: audio.transcript -> (OpenAI) -> tts.speak`
- Line 76: `SUB = BusSub("audio.transcript")`
- Line 95: `log("CHAT: start (sub audio.transcript -> pub tts.speak)")`

#### `apps/draw/face_primitives.py`

- Line 182: `"record": 0.08,`

#### `apps/nlu/main.py`

- Line 8: `audio.transcript {"text":"...", "lang":"pl", "source":"voice", "is_final":true?}`
- Line 43: `SUB = BusSub("audio.transcript")`
- Line 229: `log("NLU v0.1: start (sub audio.transcript → pub motion.cmd)")`

#### `apps/voice/__init__.py`

- Line 2: `from .audio import ALSAError  # re-eksport z podsystemu audio`

#### `apps/voice/asr.py`

*21 references found. Showing first 5:*

- Line 9: `import wave`
- Line 34: `# LOCAL HTTP (prosty REST: POST audio/wav -> JSON {text, language})`
- Line 37: `content_type: str | None = None  # domyślnie "audio/wav"`
- Line 48: `# Pomocnicze narzędzia audio`
- Line 56: `def _pcm_to_wav_bytes(audio: bytes, sample_rate: int) -> bytes:`

#### `apps/voice/audio/__init__.py`

- Line 1: `# apps/voice/audio/__init__.py`
- Line 2: `"""Audio package for Rider-Pi voice (ALSA helpers, capture/playback, errors)."""`
- Line 5: `from .alsa import ensure_free, probe_devices, reset_streams, resolved_alsa`

#### `apps/voice/audio/alsa.py`

*22 references found. Showing first 5:*

- Line 1: `# apps/voice/audio/alsa.py`
- Line 2: `"""ALSA device management and pre-flight checks for Rider-Pi voice assistant.`
- Line 5: `- Probing available ALSA devices and aliases`
- Line 32: `"""Probe available ALSA devices and log information."""`
- Line 53: `logger.event("alsa.probe.success", cards_count=len(result["cards"]), devices_count=len(result["devic...`

#### `apps/voice/audio/capture.py`

- Line 1: `# apps/voice/audio/capture.py`
- Line 21: `Konfiguracja wejścia audio (ALSA/arecord RAW PCM).`
- Line 24: `- backend: nazwa backendu, obecnie wspieramy "alsa"`
- Line 25: `- device: urządzenie ALSA, np. "wm8960_in" (alias dsnoop) lub "plughw:wm8960soundcard,0"`
- Line 29: `- buffer_seconds: dodatkowy bufor dla ALSA/arecord (sekundy, 0.0 ⇒ brak)`
- Line 38: `backend: str = "alsa"`
- Line 96: `Stabilne przechwytywanie PCM przez ALSA (arecord → stdout).`
- Line 230: `backend = (self.config.backend or "alsa").lower()`
- Line 231: `if backend != "alsa":`

#### `apps/voice/audio/errors.py`

- Line 1: `# apps/voice/audio/errors.py`
- Line 2: `"""Error classes for the audio subsystem (single source of truth)."""`
- Line 8: `"""ALSA-related errors (canonical definition used across the package)."""`

#### `apps/voice/audio/playback.py`

*35 references found. Showing first 5:*

- Line 1: `""" "Audio playback utilities for Rider-Pi voice assistant.`
- Line 3: `Provides clean, focused playback functionality without complex caching.`
- Line 20: `from .alsa import resolved_alsa`
- Line 25: `"""Configuration for audio playback."""`
- Line 27: `# accepted: "auto" | "pulse" | "alsa" | "aplay" | "paplay"`

#### `apps/voice/cli.py`

*18 references found. Showing first 5:*

- Line 24: `import wave`
- Line 171: `if getattr(args, "playback", None):`
- Line 172: `overrides = _merge(overrides, voice_config.override_from_pairs("playback", args.playback))`
- Line 200: `overrides = _merge(overrides, {"playback": {"ding": {"enabled": ding == "on"}}})`
- Line 202: `# save-audio`

#### `apps/voice/cli_commands.py`

*28 references found. Showing first 5:*

- Line 17: `import wave`
- Line 23: `from .audio.playback import PlaybackConfig, play_bytes`
- Line 47: `listen.add_argument("--playback", nargs="*")`
- Line 51: `listen.add_argument("--save-audio", nargs="*")`
- Line 63: `ptt.add_argument("--playback", nargs="*")`

#### `apps/voice/config_loader.py`

- Line 21: `for sec in ("asr", "chat", "tts", "nlu", "playback"):`
- Line 93: `"playback": {"backend", "device", "volume"},`
- Line 152: `"playback": {"aplay"},`
- Line 413: `pb = data.get("playback", {}) if isinstance(data.get("playback"), dict) else {}`
- Line 417: `self.validation_errors.append("Field 'playback.volume' must be an integer")`
- Line 419: `self.validation_errors.append("Field 'playback.volume' must be <= 100")`
- Line 421: `self.validation_errors.append("Field 'playback.volume' must be >= 0")`

#### `apps/voice/errors.py`

- Line 19: `"""Audio capture/playback related errors."""`
- Line 31: `"""ALSA-specific errors."""`
- Line 37: `"""Audio capture errors."""`
- Line 43: `"""Audio playback errors."""`
- Line 58: `"""Invalid audio format configuration or mismatch."""`

#### `apps/voice/local_io.py`

- Line 7: `import wave`

#### `apps/voice/piper_compat.py`

- Line 2: `import wave`

#### `apps/voice/rt_protocol.py`

*13 references found. Showing first 5:*

- Line 41: `RESPONSE_AUDIO_DELTA = "response.audio.delta"`
- Line 42: `RESPONSE_AUDIO_DONE = "response.audio.done"`
- Line 84: `input_sample_rate: Input audio sample rate in Hz (default: 16000)`
- Line 85: `output_sample_rate: Output audio sample rate in Hz (default: 16000)`
- Line 90: `modalities: List of modalities (default: ["text", "audio"])`

#### `apps/voice/session_prefs.py`

- Line 7: `- Modalities (text, audio)`
- Line 9: `- Input/output audio formats (sample_rate, channels)`
- Line 42: `modalities: List of modalities (e.g., ["text", "audio"])`
- Line 45: `input_sample_rate: Input audio sample rate in Hz (default: 16000)`
- Line 46: `output_sample_rate: Output audio sample rate in Hz (default: 16000)`
- Line 90: `# Modalities (default: text + audio)`
- Line 91: `modalities = ["text", "audio"]`

#### `apps/voice/stream/handlers.py`

- Line 22: `from ..audio.playback import PlaybackConfig`
- Line 160: `prefs_dict.setdefault("modalities", ["audio", "text"])`
- Line 176: `# Wyjście audio – PCM16 (pasuje do naszego playera stream.pcm16)`
- Line 296: `# ── AUDIO OUT (PCM16) ────────────────────────────────────────────`
- Line 297: `if msg_type in ("response.output_audio.delta", "response.audio.delta"):`
- Line 303: `self.logger.event("audio.delta.b64_error", error=str(e))`
- Line 312: `elif msg_type in ("response.output_audio.completed", "response.audio.done"):`
- Line 472: `from ..audio.playback import play_ding`

#### `apps/voice/stream/playout.py`

*11 references found. Showing first 5:*

- Line 2: `"""Audio capture and TTS playback worker threads for streaming voice service.`
- Line 5: `- Audio capture (microphone → queue)`
- Line 6: `- TTS playback (queue → audio output)`
- Line 17: `from ..audio.capture import CaptureConfig`
- Line 18: `from ..audio.playback import PlaybackConfig`

#### `apps/voice/stream/state.py`

- Line 20: `ARMING = auto()  # Preparing to record (ding, etc.)`
- Line 21: `RECORDING = auto()  # Capturing audio`
- Line 33: `DING_COMPLETE = auto()  # Ready to record after ding`
- Line 36: `COMMIT_AUDIO = auto()  # Force commit current audio`
- Line 38: `TTS_START = auto()  # TTS playback started`
- Line 39: `TTS_COMPLETE = auto()  # TTS playback finished`
- Line 227: `"""Check if currently recording audio."""`

#### `apps/voice/stream/svc_streaming.py`

*21 references found. Showing first 5:*

- Line 9: `- StreamPlayoutMixin: Audio capture and TTS playback workers`
- Line 24: `from ..audio.capture import CaptureConfig`
- Line 25: `from ..audio.playback import PlaybackConfig`
- Line 78: `# Audio settings`
- Line 87: `audio_cfg = stream_cfg.get("audio", {})`

#### `apps/voice/stream_chunks.py`

- Line 3: `Audio chunk processing for streaming voice service.`
- Line 19: `from .audio.capture import CaptureConfig`
- Line 31: `"""Handles audio chunk processing for streaming."""`
- Line 40: `"""Process audio chunk and encode for WebSocket transmission.`
- Line 66: `"""Create audio buffer commit message."""`
- Line 72: `Uwaga: format audio konfigurujemy w session.update (nie tutaj).`
- Line 106: `"""Decode base64 audio data from WebSocket message (RT API variants).`

#### `apps/voice/svc_audio.py`

*17 references found. Showing first 5:*

- Line 2: `"""Voice service audio I/O adapter - ALSA, capture, playback, ding."""`
- Line 13: `from .audio.capture import AudioCapture, CaptureConfig, CaptureError`
- Line 14: `from .audio.playback import PlaybackConfig, play_ding as playback_play_ding`
- Line 48: `"""Capture audio @16kHz mono; returns bytes for transcribe_file()."""`
- Line 54: `audio = b""`

#### `apps/voice/svc_bus.py`

- Line 61: `self._bus_pub.publish("audio.transcript", payload, add_ts=True)`

#### `apps/voice/svc_file.py`

*28 references found. Showing first 5:*

- Line 21: `import wave`
- Line 30: `from .audio.capture import AudioCapture, CaptureConfig, CaptureError`
- Line 31: `from .audio.playback import PlaybackConfig, play_ding`
- Line 98: `audio: bytes | None`
- Line 155: `# CAPTURE — domyślnie ALSA (nie 'dummy')`

#### `apps/voice/tts.py`

*36 references found. Showing first 5:*

- Line 9: `import wave`
- Line 15: `from .audio.playback import PlaybackConfig, PlaybackError, play_bytes, start_stream`
- Line 37: `accept: str | None = None  # np. "audio/wav" | "audio/mpeg" | "application/octet-stream"`
- Line 43: `audio: bytes | None = None`
- Line 182: `playback: PlaybackConfig,`

#### `apps/voice/voice_logging.py`

- Line 7: `def format(self, record: logging.LogRecord) -> str:`
- Line 9: `"ts": datetime.utcfromtimestamp(record.created).isoformat(timespec="milliseconds") + "Z",`
- Line 10: `"level": record.levelname,`
- Line 11: `"name": record.name,`
- Line 12: `"msg": record.getMessage(),`
- Line 17: `for k, v in record.__dict__.items():`

#### `apps/voice/web.py`

*19 references found. Showing first 5:*

- Line 14: `import wave`
- Line 119: `# Pomocniki audio (minimalne; kompatybilne z Py3.9)`
- Line 161: `def _decode_with_tool_to_wav(audio: bytes) -> bytes | None:`
- Line 170: `input=audio,`
- Line 205: `# ── audio shaping: fade & tail ────────────────────────────────────────────────`


### config/

#### `config/alsa/aliases.toml`

- Line 1: `# Rider-Pi / ALSA alias map (minimal, kanoniczny)`

#### `config/alsa/preflight.sh`

*22 references found. Showing first 5:*

- Line 2: `# config/alsa/preflight.sh — ALSA device pre-flight check and cleanup`
- Line 4: `# This script ensures ALSA devices are available before starting audio applications.`
- Line 12: `#   config/alsa/preflight.sh [--force] [--capture DEVICE] [--playback DEVICE]`
- Line 16: `#   config/alsa/preflight.sh --capture wm8960_in --playback wm8960_out`
- Line 19: `#   config/alsa/preflight.sh --force --capture wm8960_in`

#### `config/alsa/wm8960-apply.sh`

- Line 2: `#config/alsa/wm8960-apply.sh`
- Line 3: `# Skrypt konfiguracyjny ALSA dla kodeka WM8960`
- Line 35: `echo "[wm8960-apply] Brak dostępnego miksera WM8960 (CTL). Urządzenia ALSA nieaktywne." >&2`
- Line 54: `amixer -D "${CTL}" sset 'Playback' 245`
- Line 55: `amixer -D "${CTL}" sset 'PCM Playback -6dB' off`

#### `config/alsa/wm8960-mixer.sh`

- Line 2: `#config/alsa/wm8960-mixer.sh`
- Line 10: `amixer -c $card sset 'Mic Boost' 2 2>/dev/null || true`

#### `config/voice.toml`

- Line 9: `[playback]`
- Line 38: `content_type = "audio/wav"`
- Line 54: `accept = "audio/wav"`

#### `config/voice_gemini_example.toml`

- Line 12: `[playback]`

#### `config/voice_gemini_file.toml`

- Line 4: `# Uwaga: walidator wymaga playback.backend = "aplay"`
- Line 13: `[playback]`
- Line 15: `device  = "wm8960_out"    # KLUCZOWE: omijamy 'default', gramy przez alias ALSA`

#### `config/voice_local_file.toml`

- Line 7: `[playback]`
- Line 16: `content_type = "audio/wav"`
- Line 36: `accept  = "audio/wav"`

#### `config/voice_openai_file.toml`

- Line 4: `# Uwaga: walidator wymaga playback.backend = "aplay"`
- Line 13: `[playback]`
- Line 15: `device  = "wm8960_out"    # KLUCZOWE: omijamy 'default', gramy przez alias ALSA`

#### `config/voice_openai_streaming.toml`

- Line 4: `# Wymaga ALSA aliasów z: config/alsa/asoundrc.wm8960 (dsnoop/dmix).`
- Line 23: `[stream.audio]`
- Line 27: `# --- AUDIO IN (MIC) ---------------------------------------------------------`
- Line 30: `backend       = "arecord"          # alternatywnie: "alsa"`
- Line 39: `# --- AUDIO OUT --------------------------------------------------------------`
- Line 40: `[playback]`
- Line 44: `# Uwaga: wrappery /usr/local/bin/mpg123 i /usr/local/bin/paplay mają kierować na ALSA (nie Pulse)`

#### `config/voice_openai_streaming_fallback.toml`

- Line 1: `# Stabilny streaming: VAD po stronie serwera + WAV + ALSA (aplay)`
- Line 9: `[playback]`


### scripts/

#### `scripts/demo/config_validation.py`

- Line 107: `loader.load("voice_openai_file.toml", overrides={"playback": {"volume": 150}})`

#### `scripts/demo/streaming.py`

- Line 68: `"audio": {"jitter_buffer_ms": 150, "barge_in": True},`
- Line 96: `"capture": {"backend": "alsa", "sample_rate": 16000},`
- Line 97: `"playback": {"backend": "alsa"},`
- Line 128: `"capture": {"backend": "alsa"},`

#### `scripts/dev/robot_dev.sh`

- Line 34: `robot_dev.sh nlu           # NLU (audio.transcript -> motion.cmd)`

#### `scripts/dev_check-legacy-imports.py`

*21 references found. Showing first 5:*

- Line 7: `- apps/voice/audio/* (to be migrated to top-level modules)`
- Line 11: `- apps/voice/capture.py (removed in PR-3, use apps.voice.audio.capture)`
- Line 12: `- apps/voice/playback.py (removed in PR-3, use apps.voice.audio.playback)`
- Line 18: `- apps/voice/audio/wavutil.py (removed - dead code)`
- Line 47: `# Files removed in PR-3 (audio/state modules)`

#### `scripts/diag_websocket-probe.py`

- Line 19: `await ws.send(json.dumps({"type": "session.update", "session": {"modalities": ["text", "audio"]}}))`

#### `scripts/sys_voice-once.sh`

- Line 25: `"$RIDER_CONFIG_DIR/alsa/wm8960-apply.sh" || {`

#### `scripts/sys_voice-stream.sh`

- Line 2: `# voice_stream_chat.sh — configure environment, free audio devices and run a realtime chat demo.`
- Line 22: `DEFAULT_ALSA="${REPO_ROOT}/config/alsa/asoundrc.wm8960"`
- Line 55: `# --- free ALSA devices --------------------------------------------------------`
- Line 56: `echo "[voice.ops] Freeing ALSA devices..."`
- Line 97: `'Powiedz: "Test transmisji audio" i zakończ odpowiedź jednym zdaniem.',`

#### `scripts/talk_assistant.sh`

- Line 17: `-H 'Content-Type: audio/wav' --data-binary @/tmp/in.wav | jq -r '.text')`

#### `scripts/talk_local.sh`

- Line 10: `-H 'Content-Type: audio/wav' --data-binary @/tmp/in.wav | jq -r '.text')`


### services/

#### `services/api_core/voice_local_proxy.py`

- Line 38: `# Proxy dekoduje i oddaje 'audio/wav' (200) lub 502 z czytelnym błędem JSON.`
- Line 100: `r2 = Response(wav, status=200, mimetype="audio/wav")`
- Line 106: `if "audio/wav" in ctype or "audio/x-wav" in ctype:`
- Line 107: `r3 = Response(body, status=200, mimetype="audio/wav")`
- Line 135: `# Wymagamy 'audio/wav' jako body. Przekazujemy 1:1 do backendu i zwracamy JSON.`
- Line 144: `if "audio/wav" not in ctype and "audio/x-wav" not in ctype:`
- Line 145: `return _cors(jsonify({"ok": False, "error": "expect audio/wav content-type"})), 400`
- Line 149: `return _cors(jsonify({"ok": False, "error": "no audio data"})), 400`
- Line 157: `req.add_header("Content-Type", "audio/wav")`


### tests/

#### `tests/config/test_config_loader.py`

- Line 44: `assert "playback" in config`
- Line 130: `"playback": {"volume": 150}  # Max is 100`
- Line 157: `overrides={"capture": {"sample_rate": 24000}, "playback": {"volume": 75}, "asr": {"model": "whisper-...`
- Line 160: `assert config_multi["playback"]["volume"] == 75`
- Line 282: `"playback",`

#### `tests/final_verification_sim3.py`

- Line 27: `"""Run a test and record result."""`

#### `tests/test_gemini_asr_tts.py`

- Line 8: `import wave`
- Line 43: `audio = _make_test_wav()`
- Line 49: `transcribe(audio, 16000, config)`
- Line 82: `result = transcribe(audio, 16000, config)`
- Line 143: `# Simulate PCM audio data (16-bit mono at 24kHz)`

#### `tests/test_session_prefs.py`

- Line 24: `assert prefs.modalities == ["text", "audio"]`
- Line 172: `modalities=["text", "audio"],`
- Line 184: `assert result["modalities"] == ["text", "audio"]`

#### `tests/test_stream_chunks.py`

- Line 6: `from apps.voice.audio.capture import CaptureConfig`
- Line 22: `backend="alsa",`
- Line 35: `assert isinstance(obj["audio"], str)`
- Line 39: `decoded = base64.b64decode(obj["audio"])`
- Line 47: `{"type": "response.audio.delta", "delta": b64},`
- Line 48: `{"type": "response.audio", "audio": b64},`

#### `tests/test_transport_logging.py`

- Line 63: `# Rate-limit audio buffer append logging`
- Line 82: `append = json.dumps({"type": "input_audio_buffer.append", "audio": "AA=="})`

#### `tests/test_tts_streaming.py`

- Line 7: `from apps.voice.audio.playback import PlaybackConfig`

#### `tests/test_voice_audio_normalize.py`

- Line 1: `"""Unit tests for audio normalization in voice streaming."""`
- Line 5: `from apps.voice.audio.capture import CaptureConfig`
- Line 13: `"""Test handling of empty audio data."""`
- Line 19: `"""Test that mono audio passes through unchanged."""`
- Line 21: `audio_data = b"\x00\x01\x02\x03" * 10  # Some test audio data`
- Line 63: `"""Test audio processing metrics and logging."""`

#### `tests/test_voice_device_config.py`

*14 references found. Showing first 5:*

- Line 1: `"""Tests for ALSA device configuration and logging.`
- Line 13: `from apps.voice.audio.capture import AudioCapture, CaptureConfig`
- Line 14: `from apps.voice.audio.playback import PlaybackConfig, _start_playback_process`
- Line 26: `# Test with full ALSA name`
- Line 32: `"""Verify playback config accepts and stores device names."""`

#### `tests/test_voice_errors.py`

- Line 36: `error = AudioError("audio error")`
- Line 50: `error = ALSAError("alsa error")`
- Line 66: `error = PlaybackError("playback error")`
- Line 82: `error = BadAudioFormat("Invalid audio format: expected PCM16, got PCM8")`
- Line 125: `backpressure_error = BackpressureExceeded("Dropped 50 audio chunks in 1 second")`

#### `tests/test_voice_integration.py`

- Line 28: `pytest.skip('Hardware/ALSA tests disabled on CI (set RUN_DEVICE_TESTS=1 to enable).')`
- Line 64: `"capture": {"backend": "alsa"},`
- Line 65: `"playback": {"backend": "alsa"},`

#### `tests/test_voice_ptt_state.py`

- Line 50: `# Ready to record`
- Line 116: `"""Test interruption during TTS playback."""`

#### `tests/test_voice_service_ui_state.py`

- Line 27: `from .playback import play_bytes`
- Line 80: `"playback": {"backend": "pulse", "alsa_device": None, "volume": 100, "ding": {"enabled": False}},`
- Line 116: `- service_impl.synthesize -> (b"audio", 16000, "wav")`
- Line 121: `monkeypatch.setattr(service_impl_mod, "synthesize", lambda *a, **k: (b"audio", 16000, "wav"), raisin...`
- Line 127: `pytest.skip('Hardware/ALSA tests disabled on CI (set RUN_DEVICE_TESTS=1 to enable).')`
- Line 161: `assert result.audio is None and result.audio_format == "" and result.sample_rate == 0`

#### `tests/test_voice_stream_ptt_defaults.py`

- Line 18: `"playback": {},`

#### `tests/test_voice_stream_smoke.py`

- Line 31: `return json.dumps({"type": "response.audio.delta", "audio": base64.b64encode(b"mock_audio").decode()...`
- Line 42: `"""Integration tests for streaming audio flow."""`
- Line 54: `"playback": {"device": "wm8960_out"},`
- Line 79: `"""Test that stereo audio gets normalized to mono."""`
- Line 96: `assert "audio" in sent_message`
- Line 98: `# Decode the base64 audio to verify it was processed`
- Line 99: `decoded_audio = base64.b64decode(sent_message["audio"])`
- Line 101: `# Mono audio should be smaller than stereo input (or at least not larger)`
- Line 158: `"playback": {},`
- Line 189: `# Send audio chunk`

#### `tests/test_voice_streaming.py`

- Line 17: `to verify proper message handling, state transitions, and audio flow.`
- Line 89: `"capture": {"backend": "alsa", "sample_rate": 16000, "channels": 1},`
- Line 90: `"playback": {"backend": "alsa"},`
- Line 96: `pytest.skip("Hardware/ALSA tests disabled on CI (set RUN_DEVICE_TESTS=1 to enable).")`
- Line 236: `"""Test audio chunk encoding and sending."""`
- Line 240: `# Test sending audio chunk`
- Line 249: `assert "audio" in msg`
- Line 253: `assert base64.b64decode(msg["audio"]) == test_audio`
- Line 267: `# Simulate the behavior that would happen in the audio capture thread`

#### `tests/test_voice_svc_stream_proxy.py`

- Line 2: `"""Tests for apps.voice.stream.svc_streaming module exports (no I/O, no ALSA)."""`
- Line 77: `"playback": {},`

#### `tests/test_voice_ws_close.py`

- Line 29: `"playback": {},`

#### `tests/verify_hardware_isolation.py`

- Line 61: `"ops",  # Legacy ops subdirs (agent/, audio/)`


---

## Robot Control

**Files with Robot Control references**: 102

### apps/

#### `apps/camera/cam_motion.py`

- Line 18: `"motion": 12.3,`
- Line 183: `motion = _motion_metric(prev_gray, gray)`
- Line 199: `"motion": motion,`
- Line 200: `"moving": bool(motion >= MOTION_THR),`

#### `apps/camera/preview_lcd.py`

- Line 619: `cmd = "sudo -n python3 scripts/sys_lcd-control.py off >/dev/null 2>&1"`
- Line 620: `cmd += " || sudo python3 scripts/sys_lcd-control.py off"`

#### `apps/chat/main.py`

- Line 78: `SYSTEM_PROMPT = "Jesteś zwięzłym asystentem robota XGO. Odpowiadaj po polsku, jednym krótkim zdaniem...`
- Line 104: `# jeśli to komenda ruchu — zostaw to NLU/Motion`

#### `apps/choreographer/__init__.py`

- Line 4: `Choreographer module — orchestrates synchronized actions across face, motion, and voice modules.`

#### `apps/choreographer/main.py`

- Line 5: `Orchestrates synchronized actions across face, motion, and voice modules.`
- Line 12: `PUB("motion") → {"type": "drive", "lx": 0.3, "az": 0.0}`

#### `apps/demos/trajectory.py`

- Line 9: `TOPIC = os.getenv("MOTION_TOPIC", "motion")`

#### `apps/main.py`

- Line 10: `Uwaga: Motion jako usługa czyta:`
- Line 11: `- /home/pi/robot/data/flags/motion.enable   → pozwolenie na ruch`
- Line 25: `MOTION_ENABLE_FLAG = FLAGS_DIR / "motion.enable"`
- Line 29: `TOPIC = os.getenv("MOTION_TOPIC", "motion")`
- Line 66: `print("[MENU] Enabling motion (flag) and running demo…")`
- Line 79: `print("[MENU] Demo done. Disabling motion (flag).")`

#### `apps/menu/main.py`

- Line 6: `Sub: ui.button, motion.state`
- Line 7: `Pub: system.mode, motion.cmd(stop), system.menu.state`
- Line 22: `SUB_MS = BusSub("motion.state")`
- Line 42: `pub("motion.cmd", {"type": "stop"})`
- Line 107: `log("Menu: start (buttons + motion.state)")`

#### `apps/motion/main.py`

*14 references found. Showing first 5:*

- Line 3: `# apps/motion/main.py`
- Line 6: `- SUB ZeroMQ (topic 'motion') z brokera (XPUB) na tcp://127.0.0.1:5556`
- Line 11: `- telemetria PUB 'motion.state' na broker (tcp://127.0.0.1:5555)`
- Line 28: `BUS_TOPIC = os.getenv("MOTION_TOPIC", "motion")`
- Line 43: `STATE_TOPIC = os.getenv("MOTION_STATE_TOPIC", "motion.state")`

#### `apps/motion/rider_control.py`

- Line 3: `apps/motion/rider_control.py — bezpieczne mikro-impulsy ruchu dla Rider-Pi`
- Line 26: `from drivers.xgo import XgoAdapter`
- Line 80: `print(f"[MOVE] forward v={self.SPEED_LIN:.2f} t={self.PULSE:.2f}")`
- Line 86: `print(f"[MOVE] backward v={self.SPEED_LIN:.2f} t={self.PULSE:.2f}")`
- Line 102: `# Szybki tryb demo z CLI: python3 -m apps.motion.rider_control`

#### `apps/motion/xgo_adapter.py`

- Line 3: `apps/motion/xgo_adapter.py — cienka warstwa nad biblioteką XGO (CM4/Rider)`
- Line 6: `Please use drivers.xgo.XgoAdapter instead.`
- Line 33: `from drivers.xgo import XgoAdapter`

#### `apps/nlu/main.py`

- Line 5: `apps/nlu/main.py — NLU v0.1 (PL → motion.cmd)`
- Line 11: `motion.cmd  {"type":"drive|spin|stop", "dir":"forward|backward|left|right", "speed":0.4, "dur":1.0}`
- Line 156: `# --- decyzja → motion.cmd ---`
- Line 173: `Zwraca dict motion.cmd lub None oraz ewentualnie nowy cur_speed (dla 'szybciej/wolniej').`
- Line 229: `log("NLU v0.1: start (sub audio.transcript → pub motion.cmd)")`
- Line 247: `_bus_publish("motion.cmd", cmd)`
- Line 248: `log(f"NLU → motion.cmd: {cmd}")`

#### `apps/safety/estop.py`

- Line 11: `MOTION_ENABLE_FLAG = FLAGS / "motion.enable"`
- Line 49: `- istnieje plik-flag 'motion.enable'.`

#### `apps/ui/config.py`

- Line 26: `def walk(prefix: str, obj: Any):`
- Line 29: `walk(f"{prefix}{k}." if prefix else f"{k}.", v)`

#### `apps/ui/manager.py`

*23 references found. Showing first 5:*

- Line 19: `MOTION_T = os.getenv("MOTION_STATE_TOPIC", "motion.state").encode()`
- Line 21: `CTRL_T = os.getenv("UI_CTRL_TOPIC", "ui.control").encode()`
- Line 26: `DIM_MODE = os.getenv("UI_DIM_MODE", "xgo").strip().lower()`
- Line 45: `if self.mode == "xgo":`
- Line 71: `log("xgo: użyję BL via bl_DutyCycle (lub ekwiwalent)")`

#### `apps/ui/overlay.py`

- Line 15: `MOTION_T = os.getenv("MOTION_STATE_TOPIC", "motion.state").encode()`
- Line 17: `CTRL_T = os.getenv("UI_CTRL_TOPIC", "ui.control").encode()`
- Line 39: `state = {"motion": {}, "vision": {}}`
- Line 56: `state["motion"] = json.loads(payload.decode("utf-8"))`
- Line 63: `m = state.get("motion", {})`
- Line 65: `lines.append(f"MOTION: en={m.get('enabled')} estop={m.get('estop')} stopped={m.get('stopped')}")`
- Line 70: `f"VISION: moving={v.get('moving')} human={v.get('human', False)} motion={v.get('motion', 0):.1f}"`

#### `apps/voice/rt_protocol.py`

- Line 106: `turn_detection = None  # PTT/manual control`

#### `apps/voice/session_prefs.py`

- Line 192: `session_dict["turn_detection"] = None  # PTT/manual control`


### common/

#### `common/pidlock.py`

- Line 8: `def single_instance(lock_path="/tmp/rider-motion.lock"):`


### config/

#### `config/choreography.toml`

- Line 22: `topic = "motion"`


### drivers/

#### `drivers/xgo/__init__.py`

- Line 2: `XGO Robot Driver`
- Line 4: `Hardware driver for XGO robot platform.`

#### `drivers/xgo/adapter.py`

- Line 3: `drivers/xgo/adapter.py — cienka warstwa nad biblioteką XGO (CM4/Rider)`
- Line 33: `# ── Import biblioteki XGO (łagodnie) ─────────────────────────────────────────`
- Line 35: `from xgolib import XGO  # typowe wejście`
- Line 39: `XGO = None  # type: ignore`
- Line 71: `self._dog = XGO(port=port, version=version)`
- Line 79: `self._dog = XGO(port=port, version="xgomini")`
- Line 81: `self._dog = XGO(port=port, version="xgolite")`
- Line 83: `self._dog = XGO(port=port, version="xgorider")`

#### `drivers/xgo/sim.py`

- Line 3: `drivers/xgo/sim.py — Simulated XGO robot adapter`
- Line 5: `Provides a software simulator for the XGO robot, compatible with XgoAdapter interface.`
- Line 13: `LOG = logging.getLogger("drivers.xgo.sim")`
- Line 18: `Simulated XGO robot adapter for testing and development without hardware.`
- Line 31: `LOG.info(f"[SIM] XGO adapter initialized (port={port}, version={version})")`
- Line 53: `"""Stop all motion."""`
- Line 76: `Simulate forward/backward motion.`


### examples/

#### `examples/demo_driver_factory.py`

- Line 27: `from drivers.xgo import get_robot_driver`
- Line 36: `"""Demonstrate XGO robot driver factory."""`
- Line 38: `LOG.info("XGO Robot Driver Demo")`
- Line 55: `# Forward motion`

#### `examples/demo_sim3_sensors.py`

- Line 65: `# Set robot in motion`
- Line 66: `robot.linear_vel = 0.5  # Move forward`

#### `examples/navigate_simulator.py`

- Line 5: `This demonstrates how to control the simulated robot via MQTT.`
- Line 17: `"""Simple navigation: move forward, turn, move forward."""`
- Line 25: `# Create publisher for control commands`
- Line 34: `pub.publish("motion", {"type": "drive", "lx": 0.3, "az": 0.0})`
- Line 40: `pub.publish("motion", {"type": "drive", "lx": 0.0, "az": 0.4})`
- Line 51: `pub.publish("motion", {"type": "stop"})`


### scripts/

#### `scripts/demo/choreographer_demo.py`

- Line 13: `# Terminal 2: Start motion module (to see motion commands)`
- Line 14: `python3 -m apps.motion.main`
- Line 61: `print("    - Motion: drive forward (lx=0.3)")`
- Line 87: `# Subscribe to all command topics and motion`
- Line 88: `sub = BusSub(["command", "motion"])`

#### `scripts/demo_trajectory.py`

- Line 10: `from drivers.xgo import XgoAdapter`

#### `scripts/dev/robot_dev.sh`

- Line 34: `robot_dev.sh nlu           # NLU (audio.transcript -> motion.cmd)`

#### `scripts/dev_bus-dump.py`

- Line 14: `TOPIC = motion`
- Line 16: `python3 scripts/dev_bus-dump.py                 # dump 'motion'`
- Line 23: `TOPIC = os.getenv("TOPIC", os.getenv("MOTION_TOPIC", "motion"))`

#### `scripts/dev_bus-pub.py`

- Line 14: `python3 scripts/dev_bus-pub.py motion.state '{"stopped": true, "last_cmd_age_ms": 1500}'`

#### `scripts/dev_bus-state.py`

- Line 10: `TOPIC = os.getenv("MOTION_STATE_TOPIC", "motion.state").encode()`

#### `scripts/dev_keyboard-sim.py`

- Line 3: `Simple keyboard control for the simulator using ZMQ bus.`
- Line 6: `W - Move forward`
- Line 7: `S - Move backward`
- Line 15: `MOTION_TOPIC - Motion control topic (default: motion)`
- Line 30: `MOTION_TOPIC = os.getenv("MOTION_TOPIC", "motion")`
- Line 52: `print("Keyboard control for simulator:")`
- Line 62: `"""Send command to motion topic."""`

#### `scripts/dev_manual-drive.py`

- Line 6: `# Spójny z apps/motion/xgo_adapter.py: impulsy blokujące (block=True),`
- Line 11: `from drivers.xgo import XgoAdapter`

#### `scripts/dev_panel-reset-safe.py`

- Line 16: `xgo = importlib.import_module("xgoscreen")`
- Line 17: `mods.append(xgo)`
- Line 18: `if hasattr(xgo, "__path__"):`
- Line 19: `for _, name, _ in pkgutil.walk_packages(xgo.__path__, xgo.__name__ + "."):`

#### `scripts/dev_send-cmd.py`

- Line 27: `send("cmd.motion.ping", {"ts": time.time()})`
- Line 31: `send("cmd.motion.forward", {"speed": 12, "runtime": 1.0})`
- Line 36: `send("cmd.motion.turn_left", {"speed": 20, "runtime": 0.8})`
- Line 41: `send("cmd.motion.stop", {})`

#### `scripts/dev_update-docs-references.py`

- Line 61: `'tools/lcdctl.py': 'scripts/sys_lcd-control.py',`
- Line 62: `'ops/lcdctl.py': 'scripts/sys_lcd-control.py',`

#### `scripts/dev_xgo-client.py`

- Line 13: `XGOClientRO — lekka biblioteka 'read-only' do odczytu sensorów XGO.`
- Line 90: `print(f"[XGO-RO] blocked read addr={hex(addr)} len={read_len}")`

#### `scripts/diag_bus-spy.py`

- Line 13: `for t in ("cmd.", "motion.", "vision."):`

#### `scripts/diag_metrics.sh`

*13 references found. Showing first 5:*

- Line 6: `web_moves=$(journalctl -u rider-web-bridge.service --since "$since" -o cat | grep -c '\[web\].*/api/...`
- Line 8: `rx=$(journalctl -u rider-motion-bridge.service --since "$since" -o cat | grep -c 'rx_cmd.move')`
- Line 9: `fwd=$(journalctl -u rider-motion-bridge.service --since "$since" -o cat | grep -c ' forward[",]')   ...`
- Line 10: `bwd=$(journalctl -u rider-motion-bridge.service --since "$since" -o cat | grep -c ' backward[",]')`
- Line 11: `tl=$(journalctl -u rider-motion-bridge.service --since "$since" -o cat | grep -c ' turn_left[",]')`

#### `scripts/diag_sensors.py`

- Line 30: `for name in ("move", "velocity", "set_velocity", "set_v", "set_speed"):`
- Line 54: `# zatrzymaj ewentualny „gait”`
- Line 66: `from xgolib import XGO`
- Line 72: `dog = XGO(port=port, version=ver)`
- Line 76: `raise RuntimeError(f"Nie mogę połączyć się z XGO: {last_err}")`

#### `scripts/diag_stream.sh`

- Line 3: `journalctl -u rider-web-bridge.service -u rider-motion-bridge.service -f -o short-iso |`

#### `scripts/diag_test-suite.sh`

- Line 55: `say "Move forward 0.7 for 0.8s"`
- Line 56: `curl -fsS -X POST "http://localhost:${STATUS_API_PORT}/api/move" \`
- Line 58: `-d '{"vx":0.7,"vy":0,"yaw":0,"duration":0.8}' >/dev/null || fail "move API failed"`

#### `scripts/diag_tests-audit.sh`

- Line 42: `# stary kontrakt ruchu wg notatek: GET /api/move|/api/stop oraz stare ścieżki`
- Line 43: `grep -E -q '/api/(move|stop)\b|/face_lcd|/st77|/lcd_presenter' "$1" 2>/dev/null`

#### `scripts/diagnose_services.sh`

- Line 13: `NAMES_ORDER=(broker web motion cam edge ssd obstacle api)  # api NA KOŃCU i TYLKO STATUS!`

#### `scripts/sim/demo_simulator.sh`

- Line 32: `echo "[4/5] Sending control commands..."`
- Line 50: `pub.send_multipart([b'motion', json.dumps({'type': 'drive', 'lx': 0.5, 'az': 0.0}).encode()])`
- Line 56: `pub.send_multipart([b'motion', json.dumps({'type': 'drive', 'lx': 0.0, 'az': 0.3}).encode()])`
- Line 62: `pub.send_multipart([b'motion', json.dumps({'type': 'stop'}).encode()])`

#### `scripts/sim/run_simulation.py`

- Line 6: `Communicates with the motion control system via MQTT bus.`
- Line 71: `# Receive control commands`

#### `scripts/sys_boot-prepare.sh`

- Line 9: `SPLASH_USE="${SPLASH_USE:-}"                 # opcjonalnie: xgo|pygame|auto`

#### `scripts/sys_cleanup.sh`

- Line 22: `# helper: git-aware move`

#### `scripts/sys_control.sh`

- Line 8: `rider-motion-bridge.service`

#### `scripts/sys_emergency-stop.py`

- Line 24: `TOPIC = os.getenv("MOTION_TOPIC", "motion")`

#### `scripts/sys_lcd-control.py`

- Line 6: `sudo python3 scripts/sys_lcd-control.py off`
- Line 7: `sudo python3 scripts/sys_lcd-control.py on`
- Line 10: `sudo python3 scripts/sys_lcd-control.py status       # szybka diagnostyka`
- Line 11: `sudo NO_SPI=1 python3 scripts/sys_lcd-control.py off # tylko podświetlenie (bez komend SPI)`
- Line 12: `sudo python3 scripts/sys_lcd-control.py off --no-spi # j.w.`
- Line 84: `print(f"[lcdctl] WARN: backlight GPIO control failed: {e}")`

#### `scripts/sys_led-control.py`

- Line 32: `_err("      spróbuj z sudo, np.:  sudo ./scripts/sys_led-control.py off")`

#### `scripts/sys_splash-info.py`

- Line 36: `USE = os.getenv("SPLASH_USE", "auto")  # xgo|pygame|auto`
- Line 265: `Bezpośredni odczyt z XGO po UART (biblioteka producenta).`
- Line 335: `_log(f"battery: XGO UART {port} -> {vv}%")`
- Line 343: `_log(f"battery: XGO UART read failed on {port}: {e}")`
- Line 603: `_log(f"logo shown (xgo): {SPLASH_LOGO} for {SPLASH_LOGO_SECONDS:.1f}s")`
- Line 607: `_log(f"logo show failed (xgo): {e}")`
- Line 637: `_log("xgo live display OK")`
- Line 708: `if not ok and use in ("xgo", "auto") and have_xgo():`

#### `scripts/sys_splash-info.sh`

- Line 2: `# Rider-Pi — unified splash wrapper (xgo/pygame/auto) with Makefile fallback + optional logo pre-sli...`

#### `scripts/sys_vision-control.sh`

- Line 2: `# Rider-Pi Vision Control Script`

#### `scripts/sys_xgo-init.py`

- Line 5: `xgo_safe_init.py — bezpieczny start/odczyt XGO:`
- Line 6: `- --backend xgolib  -> używa oryginalnego xgolib.XGO (może szarpnąć w __init__)`
- Line 38: `Best-effort wyciszenie ruchów dla xgolib (i tak __init__ XGO robi reset()).`
- Line 59: `"move",`
- Line 96: `from xgolib import XGO`
- Line 102: `dog = XGO(port=port, version=ver)`
- Line 127: `# Uwaga: XGO.__init__ robi reset() -> jednorazowe szarpnięcie jest niestety nie do uniknięcia.`

#### `scripts/systemd-sync.sh`

- Line 19: `"rider-motion-bridge.service"`


### services/

#### `services/api_core/camera.py`

- Line 62: `resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"`
- Line 130: `resp.headers["Cache-Control"] = "no-store, max-age=0"`

#### `services/api_core/compat.py`

*26 references found. Showing first 5:*

- Line 42: `CONTROL_HTML = os.path.abspath(os.path.join(BASE_DIR, "web", "control.html"))`
- Line 242: `"xgo": {`
- Line 384: `# nazwy wspierane: motion.enable, estop.on`
- Line 391: `motion = os.path.isfile(_flag_path("motion.enable"))`
- Line 392: `return {"estop": estop, "motion_enable": motion}`

#### `services/api_core/control_api.py`

- Line 18: `C.bus_pub("cmd.move", {"vx": vx, "vy": vy, "yaw": yaw, "duration": duration, "ts": time.time()})`
- Line 50: `C.bus_pub("cmd.move", {"vx": vx, "yaw": yaw, "duration": dur, "ts": ts})`
- Line 60: `C.bus_pub("cmd.move", {"vx": 0.0, "yaw": yaw, "duration": dur, "ts": ts})`
- Line 94: `C.bus_pub("cmd.move", {"vx": vx, "yaw": yaw, "duration": ms / 1000.0, "ts": time.time()})`

#### `services/api_core/control_proxy.py`

*19 references found. Showing first 5:*

- Line 2: `"""Helpers for forwarding control commands to the motion bridge.`
- Line 33: `resp.headers["Access-Control-Allow-Origin"] = "*"`
- Line 34: `resp.headers["Access-Control-Allow-Headers"] = "Content-Type"`
- Line 35: `resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"`
- Line 51: `"""Forward a GET request to the motion bridge."""`

#### `services/api_core/dashboard.py`

- Line 23: `return Response("<h1>control.html missing</h1>", mimetype="text/html"), 404`

#### `services/api_core/device_status.py`

- Line 34: `"motion_enable": _flag_on("motion.enable"),`
- Line 52: `"xgo": {"connected": None, "last_telemetry_ts": None},`

#### `services/api_core/devices.py`

- Line 94: `for t in ("vision.", "camera.", "motion.bridge.", "motion.", "cmd.", "devices.", "xgo."):`
- Line 118: `if topic.startswith("devices.xgo"):`
- Line 119: `suffix = topic[len("devices.xgo") :].lstrip(".")`
- Line 155: `if topic.startswith("xgo."):`
- Line 156: `suffix = topic[len("xgo.") :].lstrip(".")`
- Line 189: `if topic.startswith("motion.bridge.telemetry"):`
- Line 197: `if topic == "motion.bridge.battery_pct":`
- Line 305: `print("[api] XGO RO connected: /dev/ttyAMA0", flush=True)`

#### `services/api_core/services_api.py`

- Line 22: `# motion / xgo`
- Line 23: `"xgo": "rider-motion-bridge.service",`
- Line 24: `"motion": "rider-motion-bridge.service",`
- Line 25: `"motion-preview": "rider-motion-bridge.service",  # jeśli masz osobny unit, podmień`

#### `services/api_core/state_api.py`

- Line 46: `"xgo": (`

#### `services/api_core/vision_api.py`

- Line 25: `resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"`

#### `services/api_core/voice_local_proxy.py`

- Line 25: `resp.headers["Access-Control-Allow-Origin"] = "*"`
- Line 26: `resp.headers["Access-Control-Allow-Headers"] = "Content-Type"`
- Line 27: `resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS,HEAD"`

#### `services/api_core/voice_proxy.py`

- Line 16: `resp.headers["Access-Control-Allow-Origin"] = "*"`
- Line 17: `resp.headers["Access-Control-Allow-Headers"] = "Content-Type"`
- Line 18: `resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"`

#### `services/api_server.py`

*15 references found. Showing first 5:*

- Line 45: `resp.headers["Access-Control-Allow-Origin"] = "*"`
- Line 46: `resp.headers["Access-Control-Allow-Headers"] = "Content-Type"`
- Line 47: `resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS,HEAD"`
- Line 157: `# control proxy`
- Line 158: `_add_rule("/api/control", view_func=control_proxy.control_proxy_handler, methods=["POST", "OPTIONS"]...`

#### `services/broker.py`

- Line 7: `- SUB-y (apps/motion) łączą się do tcp://*:5556`

#### `services/motion_bridge.py`

*41 references found. Showing first 5:*

- Line 5: `Rider-Pi – Motion Bridge (deadman auto-stop + debounce + RX echo + compat adapter)`
- Line 13: `* NOWE:  cmd.move {vx,vy,yaw|az,duration,ts}, cmd.stop {}`
- Line 14: `* STARE: cmd.motion.forward/backward/left/right/turn_left/turn_right/stop {speed,runtime}`
- Line 15: `Mapuje na wywołania XGO; skręt bezpośrednio na vendorowe turnleft/turnright(step).`
- Line 17: `* motion.bridge.event {event, detail}`

#### `services/motion_cmd_shim.py`

- Line 16: `sub.setsockopt_string(zmq.SUBSCRIBE, "motion.cmd")`
- Line 22: `print("[shim] START: motion.cmd → cmd.move", flush=True)`
- Line 43: `pub.send_string(f"cmd.move {json.dumps(out, ensure_ascii=False)}")`
- Line 44: `print("[shim] motion.cmd → cmd.move:", out, flush=True)`

#### `services/web_motion_bridge.py`

*12 references found. Showing first 5:*

- Line 5: `HTTP → ZMQ bridge dla Rider-Pi (zgodny z motion_bridge.py) + kompatybilny /control.`
- Line 8: `GET  /api/move?dir=forward|backward|left|right[&v=0..1][&w=0..1][&t=sek]`
- Line 13: `POST /control    {type: drive|spin|stop, ...}  // kompatybilne z dashboardem`
- Line 24: `TOPIC_MOVE = os.getenv("TOPIC_MOVE", "cmd.move")`
- Line 35: `# XGO adapter (opcjonalnie – best effort)`


### sim/

#### `sim/robot.py`

- Line 3: `Simulated Robot - Virtual robot model with MQTT control integration`
- Line 19: `CONTROL_TOPIC = os.getenv("MOTION_TOPIC", "motion")`
- Line 24: `Virtual robot that receives control commands via MQTT and simulates physics.`
- Line 41: `"""Initialize MQTT subscriber for control commands."""`
- Line 54: `"""Receive and process control commands from MQTT."""`
- Line 73: `"""Process a control command."""`

#### `sim/world.py`

- Line 289: `"Control via MQTT:",`
- Line 290: `f"  Topic: {os.getenv('MOTION_TOPIC', 'motion')}",`


### tests/

#### `tests/acceptance_criteria.py`

- Line 66: `print("\n[AC3] MQTT message on 'motion' topic causes robot movement")`
- Line 84: `criteria.append(("AC3", True, "✓ MQTT commands control robot movement"))`

#### `tests/api_compare.sh`

- Line 19: `# uniwersalny 'walk' i kanonizacja: liczby->0, stringi->"X"`
- Line 20: `JQ_WALK='def walk(f):`
- Line 29: `JQ_CANON="$JQ_WALK walk(if type==\"number\" then 0 elif type==\"string\" then \"X\" else . end)"`

#### `tests/api_diag.sh`

- Line 33: `$(basename "$0") flags         # cykl flag: motion.enable i estop.on (on/off)`
- Line 102: `echo "== enable motion ==";     $CURL -X POST "$BASE/api/flags/motion.enable/on" | pp`
- Line 107: `$CURL -X POST "$BASE/api/flags/motion.enable/off" | pp`

#### `tests/burst_web_moves.sh`

- Line 32: `if curl -sf -X "${METHOD}" "${BASE}/api/move" -H "$HDR" \`

#### `tests/cascade_forward.sh`

- Line 13: `curl -fsS -X POST "$API/api/control" -H 'Content-Type: application/json' \`

#### `tests/count_rx_since.sh`

- Line 5: `echo "== Zdarzenia BRIDGE (rider-motion-bridge.service) od: ${SINCE} =="`
- Line 6: `journalctl -u rider-motion-bridge.service --since "${SINCE}" --no-pager \`
- Line 8: `/rx_cmd\.move/{rx++}`
- Line 9: `/skip_cmd\.move/{sk++}`
- Line 12: `END{printf "rx_cmd.move=%d, skip_cmd.move=%d, auto_stop=%d, stop=%d\n", rx, sk, as, st}'`
- Line 17: `/GET \/api\/move|POST \/api\/move/{m++}`
- Line 19: `END{printf "/api/move=%d, /api/stop=%d\n", m, s}'`

#### `tests/diag_snapshot.sh`

- Line 31: `SERVICES=(rider-broker.service rider-web-bridge.service rider-motion-bridge.service rider-api.servic...`

#### `tests/env.sh`

- Line 30: `local code; code="$(http_code POST "${BASE_URL}/api/move" "${payload}")"`
- Line 37: `req_get "/api/move?dir=${dir}&v=${v}&w=${w}&t=${t}"`
- Line 46: `req_post "/api/move" "${payload}"`

#### `tests/reboot_safety_check.sh`

- Line 21: `NEEDED=(rider-broker.service rider-motion-bridge.service rider-web-bridge.service rider-api.service)`
- Line 30: `systemd-analyze verify "$ROOT/systemd"/rider-{broker,motion-bridge,web-bridge,api}.service || die "v...`
- Line 36: `sudo systemctl restart rider-motion-bridge.service`
- Line 46: `echo "== smoke move =="`
- Line 47: `curl -fsS "http://127.0.0.1:8080/api/move?dir=forward&v=0.12&t=0.12" >/dev/null || die "move fail"`

#### `tests/test_choreographer_integration.py`

- Line 30: `# Should have published commands to face and motion`
- Line 33: `# Check that at least one call was to face or motion`
- Line 35: `assert any("face" in topic or "motion" in topic for topic in topics_called)`

#### `tests/test_choreographer_mapping.py`

- Line 138: `{"topic": "command.motion.action", "payload": {"action": "wag"}},`

#### `tests/test_drivers_import.py`

- Line 14: `"""Test importing XGO driver from new location."""`
- Line 15: `from drivers.xgo import XgoAdapter`
- Line 20: `"""Test backward compatibility for XGO driver."""`
- Line 21: `from apps.motion.xgo_adapter import XgoAdapter`

#### `tests/test_face_anim_api.py`

- Line 158: `assert rv.headers.get("Access-Control-Allow-Origin") == "*"`
- Line 159: `assert "GET" in rv.headers.get("Access-Control-Allow-Methods", "")`

#### `tests/test_motion.py`

- Line 14: `from drivers.xgo import XgoAdapter  # noqa: E402`
- Line 20: `print("[ERR] Adapter/XGO niedostępny.")`

#### `tests/test_motion_bus.py`

- Line 6: `Tester ścieżki BUS → motion.main → adapter → robot.`
- Line 8: `Wysyła komendy na topic 'motion.cmd' i (jeśli dostępne) nasłuchuje 'motion.echo'.`
- Line 15: `Uwaga: pętla apps.motion.main musi być uruchomiona.`
- Line 26: `CMD_TOPIC = "motion.cmd"`
- Line 27: `ECHO_TOPIC = "motion.echo"`
- Line 81: `# (opcjonalnie) jeżeli motion.main obsługuje komendę 'spin':`

#### `tests/test_no_underscore_apps_dependency.py`

- Line 38: `for root, _dirs, files in os.walk(base):`

#### `tests/test_simulation_toggle.py`

- Line 26: `"""Test XGO driver returns physical implementation by default."""`
- Line 29: `from drivers.xgo import get_robot_driver`
- Line 37: `"""Test XGO driver returns simulated implementation when RIDER_SIMULATOR=1."""`
- Line 43: `import drivers.xgo`
- Line 45: `importlib.reload(drivers.xgo)`
- Line 54: `from drivers.xgo.sim import SimulatedXgoAdapter`
- Line 62: `# Test motion methods don't crash`

#### `tests/test_simulator_integration.py`

- Line 38: `# Create publisher for control commands`
- Line 51: `pub.publish("motion", {"type": "drive", "lx": 0.5, "az": 0.0})`
- Line 76: `pub.publish("motion", {"type": "drive", "lx": 0.0, "az": 0.5})`
- Line 84: `pub.publish("motion", {"type": "stop"})`

#### `tests/test_simulator_mqtt.py`

- Line 3: `Integration test for simulator with MQTT control.`
- Line 30: `MOTION_TOPIC = "motion"`

#### `tests/test_simulator_robot.py`

- Line 32: `"""Test linear motion physics."""`
- Line 40: `# Should move 1 meter in X direction (angle=0 is right)`
- Line 49: `"""Test angular motion physics."""`
- Line 66: `"""Test combined linear and angular motion."""`
- Line 74: `# Should move forward while turning`

#### `tests/test_suite.sh`

- Line 18: `run touch ~/robot/data/flags/motion.enable`
- Line 32: `run journalctl -u rider-motion-bridge -n 150 --no-pager | egrep -i 'rx_cmd.move|forward|stop|drop_ol...`

#### `tests/test_web_routes.py`

- Line 122: `cache_control = r.headers.get("Cache-Control", "").lower()`
- Line 135: `"/web/control.html",`

#### `tests/watch.sh`

- Line 26: `tmux send-keys -t "$SESSION":0.0 "journalctl -fu rider-motion-bridge.service" C-m`
- Line 40: `stdbuf -oL journalctl -fu rider-motion-bridge.service > "$LOGDIR/motion.log" 2>&1 & echo $! > "$LOGD...`
- Line 47: `exec tail -F "$LOGDIR"/{motion,web,api,ports,events}.log`

#### `tests/web_control_diag.sh`

- Line 23: `curl -sf -X POST "${BASE}/api/move" -H "$HDR" -d "{\"vx\": ${VX},  \"vy\":0, \"yaw\":0, \"duration\"...`
- Line 30: `curl -sf -X POST "${BASE}/api/move" -H "$HDR" -d "{\"vx\": -${VX}, \"vy\":0, \"yaw\":0, \"duration\"...`
- Line 45: `journalctl -u rider-motion-bridge.service -n 120 --no-pager || true`

#### `tests/web_move_smoke.sh`

- Line 19: `curl -s -o /dev/null -w "%{http_code}\n" "${BASE}/api/move?dir=forward" | grep -q '^405$' && echo " ...`
- Line 24: `echo "== SAFE: POST move forward (mikro-impuls) =="`
- Line 25: `curl -sf -X POST "${BASE}/api/move" -H "$HDR" \`
- Line 32: `echo "== SAFE: POST move backward (mikro-impuls) =="`


---

## Display Hardware

**Files with Display Hardware references**: 83

### apps/

#### `apps/camera/preview_lcd.py`

- Line 3: `Rider-Pi: podgląd kamery na 2" SPI LCD + (opcjonalnie) detekcja obiektów i publikacja na bus.`
- Line 8: `- Respektuje tryb headless:       DISABLE_LCD=1 lub NO_DRAW=1 → nie rysuje na LCD`
- Line 43: `from PIL import Image  # PIL używany do LCD`
- Line 124: `"lcd": {"active": bool(lcd_active), "no_draw": ENV_NO_DRAW, "rot": ROT},`
- Line 131: `# ── LCD (opcjonalnie; jeśli wyłączone, jedziemy headless)`
- Line 146: `print("[preview] LCD niedostępny lub biblioteka brakująca:", e, file=sys.stderr)`
- Line 505: `f"[preview] Start. LCD={'ON' if (LCD_ok and not ENV_NO_DRAW) else 'OFF (headless)'}; "`
- Line 599: `# Wyświetlenie na LCD`
- Line 616: `# zgaś LCD po wyjściu (best-effort)`

#### `apps/camera/preview_lcd_hybrid.py`

- Line 7: `# + wysyła camera.heartbeat + snapshoty RAW/proc/LCD/LCD_fb`
- Line 52: `# --- LCD (opcjonalnie) ---`
- Line 70: `lcd = LCD_2inch()`
- Line 71: `lcd.rotation = 0  # obraz już obrócony w OpenCV`
- Line 72: `return lcd`
- Line 83: `from PIL import Image`

#### `apps/camera/preview_lcd_ssd.py`

- Line 7: `# + ramki na LCD, + heartbeat, + publikacja vision.person (tylko przy realnym trafieniu)`
- Line 93: `lcd = LCD_2inch()`
- Line 94: `lcd.rotation = 0`
- Line 95: `return lcd`
- Line 107: `from PIL import Image`
- Line 372: `# LCD`

#### `apps/camera/preview_lcd_takeover.py`

- Line 10: `from PIL import Image`
- Line 31: `# --- LCD init ---`
- Line 38: `lcd = LCD_2inch()`
- Line 39: `lcd.rotation = 0`
- Line 40: `return lcd`

#### `apps/camera/ssd_preview_writer.py`

- Line 4: `# SSD preview + pewny zapis RAW/PROC do /home/pi/robot/snapshots (atomowo) + LCD`
- Line 64: `from PIL import Image`
- Line 67: `lcd = LCD_2inch()`
- Line 68: `lcd.rotation = 0`
- Line 70: `lcd.ShowImage(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))`
- Line 123: `f"[start] SNAP_DIR={SNAP_DIR} ROT={ROT} LCD={'off' if DISABLE_LCD else 'on'} SCORE>={SCORE} EVERY={E...`

#### `apps/draw/face_primitives.py`

- Line 7: `# apps/draw/face_primitives.py — prymitywy rysowania buźki Rider-Pi (PIL).`

#### `apps/hw/sink_lcd.py`

*16 references found. Showing first 5:*

- Line 4: `apps/hw/sink_lcd.py — obsługa wyświetlacza LCD dla buźki Rider-Pi.`
- Line 5: `Dwie ścieżki: RAW (push_rgb565) i fallback (show_image PIL.Image).`
- Line 11: `from PIL import Image  # noqa: E402`
- Line 31: `import spidev`
- Line 89: `Szybka ścieżka: wysyła surowe dane RGB565 do LCD przez SPI.`

#### `apps/menu/main.py`

- Line 5: `apps/menu/main.py — proste menu na 4 przyciski (bez LCD)`
- Line 28: `"screen": "home",`
- Line 49: `"screen": state["screen"],`
- Line 51: `"items": HOME_ITEMS if state["screen"] == "home" else [],`
- Line 64: `if state["screen"] == "home":`

#### `apps/ui/face/__main__.py`

- Line 12: `from PIL import Image, ImageDraw`
- Line 119: `for name in ("render", "display", "main", "run"):`
- Line 123: `fn({"backend": "lcd", "png_bytes": png, "outfile": outfile})`
- Line 147: `backend = os.getenv("FACE_BACKEND", "lcd").lower()`
- Line 180: `# 1) render buźki`

#### `apps/ui/face/controller.py`

- Line 10: `from PIL import Image`
- Line 256: `"""Zwraca PIL.Image (używane przez scripts/dev_face-lcd-direct.py)."""`
- Line 261: `from PIL import ImageDraw`

#### `apps/ui/face/driver/__init__.py`

- Line 1: `from drivers.lcd import Driver, PanelCfg, make_driver`

#### `apps/ui/face/driver/mock.py`

- Line 6: `from PIL import Image`
- Line 35: `# Nie blokuj testu jeśli numpy/PIL nie działa`

#### `apps/ui/face/face_io.py`

- Line 6: `from PIL import Image`

#### `apps/ui/face/panel_cfg.py`

- Line 1: `from drivers.lcd.panel_cfg import PanelCfg`

#### `apps/ui/face/renderer.py`

- Line 6: `Brak cyklicznych zależności (nie importuje controller ani LCD).`
- Line 11: `from PIL import Image, ImageDraw  # noqa: E402`

#### `apps/ui/manager.py`

*12 references found. Showing first 5:*

- Line 13: `from PIL import Image`
- Line 50: `lcd = LCD_2inch.LCD_2inch()`
- Line 51: `lcd.Init()`
- Line 52: `self._xgo_lcd = lcd`
- Line 53: `w = int(getattr(lcd, "height", 240))`

#### `apps/ui/overlay.py`

- Line 33: `pygame.display.init()`
- Line 35: `screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)`
- Line 61: `screen.fill((0, 0, 0))`
- Line 75: `img = font.render(s, False, (200, 200, 200))`
- Line 76: `screen.blit(img, (20, y))`
- Line 78: `pygame.display.flip()`

#### `apps/vision/detector_hog.py`

- Line 10: `from PIL import Image`


### common/

#### `common/cam_heartbeat.py`

- Line 49: `"lcd": {"active": True, "presenting": bool(presenting), "rot": self.rot},`

#### `common/snap.py`

- Line 5: `# Prosty „snapper”: zapisuje migawki JPG do katalogu (RAW/PROC/LCD/LCD_FB)`
- Line 11: `#   SNAP_LCD_EVERY=1         - co ile sekund zapisywać „nasz render LCD”`
- Line 18: `#   <SNAP_DIR>/lcd.jpg`
- Line 42: `"lcd": float(os.getenv("SNAP_LCD_EVERY", lcd_every if lcd_every is not None else 1.0) or 0),`
- Line 53: `self.fb_bpp = 16  # najczęściej 16bpp (RGB565) na małych LCD`
- Line 96: `"""Zapis tego, co my renderujemy na LCD (z posiadanego obrazu BGR)."""`
- Line 97: `if not self._should("lcd"):`
- Line 99: `return self._save("lcd", frame_bgr)`
- Line 109: `rgb = np.array(pil_img)  # PIL RGB -> np.uint8 [H,W,3]`
- Line 113: `return self._save("lcd", bgr)`


### config/

#### `config/agent/constraints.txt`

- Line 2: `Pillow==11.3.0`


### drivers/

#### `drivers/lcd/__init__.py`

- Line 2: `LCD Display Driver`
- Line 4: `Hardware driver for LCD display (ILI9xx-based panels).`
- Line 16: `"""Base driver interface for LCD display."""`
- Line 27: `Factory function to create LCD driver instances.`
- Line 53: `Factory function to get the appropriate LCD driver.`
- Line 61: `LCD driver instance (real or simulated)`
- Line 71: `# Try to import the real LCD renderer`

#### `drivers/lcd/driver_ili9xx.py`

*24 references found. Showing first 5:*

- Line 23: `from PIL import Image`
- Line 53: `for extra in ("xgoscreen.lcdconfig", "xgoscreen.lcd", "xgoscreen.screen"):`
- Line 66: `pres = any(callable(getattr(cls, m, None)) for m in ("ShowImage", "show_image", "display", "put", "p...`
- Line 77: `if "lcd" in n or "display" in n or "panel" in n:`
- Line 103: `for name in ("ShowImage", "show_image", "display", "put", "present"):`

#### `drivers/lcd/mock.py`

- Line 6: `from PIL import Image`
- Line 35: `# Nie blokuj testu jeśli numpy/PIL nie działa`

#### `drivers/lcd/sim.py`

*14 references found. Showing first 5:*

- Line 3: `drivers/lcd/sim.py — Simulated LCD display driver`
- Line 5: `Provides a software simulator for LCD display, compatible with the driver interface.`
- Line 15: `LOG = logging.getLogger("drivers.lcd.sim")`
- Line 20: `Simulated LCD driver for testing without hardware.`
- Line 22: `Logs display operations and optionally saves frames to /tmp for inspection.`


### examples/

#### `examples/demo_driver_factory.py`

- Line 26: `from drivers.lcd import PanelCfg, get_lcd_driver`
- Line 83: `"""Demonstrate LCD driver factory."""`
- Line 85: `LOG.info("LCD Driver Demo")`
- Line 93: `lcd = get_lcd_driver(cfg)`
- Line 94: `LOG.info(f"Driver type: {type(lcd).__name__}")`
- Line 96: `# Try to create a simple image (requires PIL)`
- Line 98: `from PIL import Image, ImageDraw`
- Line 107: `lcd.ShowImage(img)`
- Line 109: `LOG.info("\n✓ LCD driver demo complete")`
- Line 111: `LOG.warning("PIL not available - skipping image test")`

#### `examples/demo_sim3_sensors.py`

- Line 88: `camera_surface = camera.render(robot.x, robot.y, robot.angle, world.wall_segments)`


### scripts/

#### `scripts/demo_weather-lcd.py`

*15 references found. Showing first 5:*

- Line 4: `Rider‑Pi — pogoda na 2" LCD (jednorazowy CLI): pobiera bieżącą pogodę z Open‑Meteo`
- Line 10: `- Dodano `--self-test` (testy offline renderera i pomiaru tekstu, bez sieci/LCD) + dodatkowe asercje...`
- Line 11: `- Fallback pomiaru tekstu (zgodność różnych wersji Pillow) i defensywne ścieżki.`
- Line 25: `from PIL import Image, ImageDraw, ImageFont`
- Line 27: `sys.stderr.write("[weather] Brak Pillow (PIL). Zainstaluj: pip3 install pillow\n")`

#### `scripts/dev/robot_dev.sh`

- Line 15: `: "${FACE_BACKEND:=lcd}"`
- Line 33: `robot_dev.sh face          # UI (LCD/TK; honoruje FACE_* ENV)`
- Line 44: `FACE_BACKEND=lcd|tk        # domyślnie lcd (gdy DISPLAY brak → tk pomijany)`

#### `scripts/dev_check-legacy-imports.py`

- Line 26: `- apps/ui/face/driver_ili9xx.py (moved to _todelete, use drivers.lcd.driver_ili9xx)`
- Line 96: `(r"from apps\.ui\.face\.driver_ili9xx\b", "apps/ui/face/driver_ili9xx.py (moved to _todelete, use dr...`

#### `scripts/dev_face-cli.py`

- Line 8: `from PIL import Image, ImageDraw`
- Line 11: `from drivers.lcd import PanelCfg, make_driver`
- Line 14: `Nowe CLI do renderowania buźki na LCD/mocka.`
- Line 46: `parser = argparse.ArgumentParser(description="Face LCD CLI (mock/spi)")`
- Line 48: `parser.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], help="Rotacja LCD (0/90/180/270...`

#### `scripts/dev_face-lcd-clean.py`

- Line 34: `for m in ("ShowImage", "show_image", "display", "blit", "put", "present")`
- Line 37: `if has_show or has_raw or name.lower().startswith("lcd"):`
- Line 111: `from PIL import Image`
- Line 119: `from PIL import Image, ImageDraw`
- Line 175: `ap = argparse.ArgumentParser(description="Prosty renderer LCD (apps/* only).")`
- Line 177: `ap.add_argument("--lcd-class")`
- Line 190: `print(f"[clean] dostępne klasy LCD: {names}")`
- Line 215: `for name in ("ShowImage", "show_image", "display", "blit", "put", "present"):`
- Line 261: `raise RuntimeError("Brak ShowImage i RAW prymitywów w klasie LCD")`

#### `scripts/dev_face-lcd-direct.py`

*45 references found. Showing first 5:*

- Line 17: `from PIL import Image`
- Line 40: `r"(img|image|frame|png|rgb|buf|buffer|disp|show|blit|push|draw|render|present|send|write|update|put)...`
- Line 115: `"drivers.lcd.driver_ili9xx",`
- Line 124: `"Nie udało się załadować żadnego modułu sterownika LCD "`
- Line 125: `"(drivers/lcd/* ani apps/ui/face/* ani _apps/ui/face_renderers.py)."`

#### `scripts/dev_face-presenter.py`

- Line 11: `from PIL import Image, ImageDraw`

#### `scripts/dev_lcd-clear.py`

- Line 8: `from PIL import Image`
- Line 41: `if getattr(c, "__name__", "").lower().find("lcd") >= 0 and hasattr(c, "ShowImage"):`

#### `scripts/dev_lcd-show-raw.py`

- Line 9: `from PIL import Image, ImageDraw`
- Line 19: `lcd = fr.LCDRenderer(fr.FaceConfig(lcd_do_init=True, lcd_rotate=0, lcd_spi_hz=SPI_HZ))`
- Line 20: `d = lcd.device`
- Line 21: `W, H = lcd.width, lcd.height`

#### `scripts/dev_lcd-testcard.py`

- Line 8: `from PIL import Image, ImageDraw`
- Line 37: `if getattr(c, "__name__", "").lower().find("lcd") >= 0 and hasattr(c, "ShowImage"):`

#### `scripts/dev_panel-nuke.py`

- Line 16: `lcd = fr.LCDRenderer(fr.FaceConfig(lcd_do_init=True, lcd_rotate=0, lcd_spi_hz=SPIHZ))`
- Line 17: `d = lcd.device`
- Line 18: `W, H = lcd.width, lcd.height`

#### `scripts/dev_panel-reset-safe.py`

- Line 24: `for extra in ("xgoscreen.lcdconfig", "xgoscreen.lcd", "xgoscreen.screen"):`
- Line 41: `for a in ("ShowImage", "show_image", "display", "blit", "put", "present")`
- Line 44: `name_ok = any(k in n.lower() for k in ("lcd", "st77", "st7789", "display", "panel"))`
- Line 52: `0 if "lcd" in kv[0].lower() else 1,`
- Line 155: `# Display ON`

#### `scripts/dev_panel-reset.py`

- Line 18: `lcd = fr.LCDRenderer(fr.FaceConfig(lcd_do_init=True, lcd_rotate=0, lcd_spi_hz=SPIHZ))`
- Line 21: `spi = getattr(getattr(lcd, "device", None), "SPI", None)`
- Line 33: `getattr(dev, "lcd", None),`
- Line 35: `getattr(dev, "display", None),`
- Line 42: `d = get_raw(lcd.device)`
- Line 64: `W = getattr(lcd, "width", 240)`
- Line 65: `H = getattr(lcd, "height", 320)`

#### `scripts/dev_update-docs-references.py`

- Line 45: `# LCD commands - prefer make targets`
- Line 47: `r'python3 (\.\/)?ops/lcdctl\.py on': 'make lcd-on',`
- Line 48: `r'python3 (\.\/)?ops/lcdctl\.py off': 'make lcd-off',`
- Line 49: `r'python3 (\.\/)?tools/lcdctl\.py on': 'make lcd-on',`
- Line 50: `r'python3 (\.\/)?tools/lcdctl\.py off': 'make lcd-off',`
- Line 76: `# Skip command mappings (like 'make lcd-on')`

#### `scripts/diag_framebuffer-grab.py`

- Line 5: `# Zrzut faktycznej zawartości LCD (framebuffer) do JPG.`
- Line 28: `from PIL import Image`
- Line 57: `# rotate clockwise: PIL rotate is counter-clockwise; use transpose helpers`
- Line 80: `parser = argparse.ArgumentParser(description='Framebuffer -> JPG (LCD 2")')`
- Line 94: `print(f"[fbgrab] ERROR: {dev} nie istnieje. Jesteś pewien, że LCD to {dev}?")`

#### `scripts/diag_lcd-raw.py`

- Line 38: `for extra in ("xgoscreen.lcdconfig", "xgoscreen.lcd", "xgoscreen.screen"):`
- Line 58: `for k in ("ShowImage", "show_image", "display", "blit", "put", "present")`
- Line 66: `# preferuj nazwy z '2inch' lub 'lcd'`
- Line 70: `0 if "lcd" in kv[0].lower() else 1,`
- Line 126: `W = getattr(dev, "width", None) or getattr(getattr(dev, "lcd", None), "width", None) or 240`
- Line 127: `H = getattr(dev, "height", None) or getattr(getattr(dev, "lcd", None), "height", None) or 320`

#### `scripts/diag_xgo-bootloader.py`

- Line 9: `lcd = LCD_2inch.LCD_2inch()`
- Line 10: `lcd.Init()`
- Line 11: `print("LCD attrs:", [n for n in dir(lcd) if not n.startswith("_")][:20], "...")`
- Line 12: `mods = [lcd, LCD_2inch, getattr(LCD_2inch, "config", None)]`
- Line 37: `fn = getattr(lcd, "bl_DutyCycle", None)`

#### `scripts/sim/run_simulation.py`

- Line 80: `# Render camera view`
- Line 81: `camera_surface = camera.render(robot.x, robot.y, robot.angle, world.wall_segments)`
- Line 84: `# Render world`
- Line 85: `world.render(robot, camera_surface)`

#### `scripts/sys_boot-prepare.sh`

*11 references found. Showing first 5:*

- Line 2: `# Rider-Pi — boot prepare: vendor cleanup + splash + LCD off`
- Line 12: `# Domyślnie przechodzimy na Makefile (lcd-off) — uwaga na spacje:`
- Line 13: `LCD_OFF_CMD="${LCD_OFF_CMD:-/usr/bin/make -C /home/pi/robot lcd-off}"`
- Line 15: `NO_KILL_DISPLAY="${NO_KILL_DISPLAY:-0}"      # 1 = NIE ubijaj lightdm/display-manager`
- Line 38: `# 3b) (opcjonalnie) kill display-manager`

#### `scripts/sys_camera-kill.sh`

- Line 2: `# camera_takeover_kill.sh — free camera/SPI and light up LCD backlight`
- Line 10: `# 1) Podświetlenie LCD (BL ON), jeśli narzędzie dostępne`

#### `scripts/sys_lcd-control.py`

- Line 3: `Rider-Pi LCD controller (2" SPI TFT) — ON/OFF (+ status, optional no-spi mode)`
- Line 96: `import spidev  # type: ignore`
- Line 186: `p = argparse.ArgumentParser(description='Rider-Pi 2" LCD ON/OFF controller')`
- Line 215: `sp_off = sub.add_parser("off", help="turn LCD off (sleep + backlight off)")`
- Line 219: `sp_on = sub.add_parser("on", help="turn LCD on (wake + backlight on)")`

#### `scripts/sys_splash-info.py`

*12 references found. Showing first 5:*

- Line 16: `from PIL import Image, ImageDraw, ImageFont`
- Line 485: `# ---------------- RENDER ----------------`
- Line 637: `_log("xgo live display OK")`
- Line 659: `screen = pygame.display.set_mode(target_size, 0, 24)`
- Line 660: `screen.fill((0, 0, 0))`

#### `scripts/sys_splash-info.sh`

- Line 41: `# PIL (Pillow) jest używany także w status splash, więc zakładamy, że jest dostępny.`
- Line 42: `from PIL import Image`
- Line 68: `# Ignoruj problemy z LCD – przejdziemy do status splash`
- Line 86: `# Fallback: kolorowa plansza na LCD`
- Line 91: `make -C "${ROOT}" lcd-black || true`

#### `scripts/sys_vendor-splash.py`

- Line 7: `from PIL import Image, ImageDraw, ImageFont`

#### `scripts/systemd-sync.sh`

- Line 24: `"rider-cam-preview.service"     # raw preview (no LCD when DISABLE_LCD=1)`


### services/

#### `services/api_core/compat.py`

- Line 83: `"lcd": {`
- Line 239: `"rot": LAST_CAMERA["lcd"].get("rot", ENV_ROT),`
- Line 240: `"no_draw": LAST_CAMERA["lcd"].get("no_draw", ENV_NO_DRAW),`

#### `services/api_core/devices.py`

- Line 222: `lcd = data.get("lcd") or {}`
- Line 223: `C.LAST_CAMERA["lcd"].update(`
- Line 231: `if k in lcd:`
- Line 232: `C.LAST_CAMERA["lcd"][k] = lcd[k]`

#### `services/api_core/face_anim.py`

- Line 12: `from PIL import Image`
- Line 28: `# ====================== SINKI (bez wczesnego LCD/SPI) ========================`
- Line 70: `"""Wybór sinka wg ENV FACE_SINK: file | lcd | null (domyślnie: file)."""`
- Line 74: `elif kind == "lcd":`
- Line 75: `# Lazy import + bezpieczny fallback (brak LCD nie wywala importu modułu przy starcie)`
- Line 81: `raise LcdNotAvailable(f"LCD sink not available: {e}") from e`
- Line 121: `# Renderer – bez konfiguracji LCD, wyłącznie PNG bytes`
- Line 127: `# Sink – wybór wg ENV; LCD zamieniamy na NullSink jeśli niedostępny`
- Line 152: `# Fallback: dekoduj PNG -> PIL.Image i przekaż`
- Line 166: `STATE["error"] = "render"`

#### `services/api_core/face_api.py`

*15 references found. Showing first 5:*

- Line 93: `from PIL import Image`
- Line 137: `"""Wyrenderuj jedną klatkę jako PIL.Image (bezpośrednio, nie PNG)."""`
- Line 144: `return r.render_image(state=state)  # PIL.Image`
- Line 169: `- sukces: {"ok": true, "out": "..."} lub {"ok": true, "used": "..."} (dla LCD)`
- Line 199: `elif b in {"lcd", "raw"}:`

#### `services/api_server.py`

- Line 61: `@app.route("/face/render", methods=["POST"])`

#### `services/last_frame_sink.py`

- Line 38: `"lcd": {"active": False},`


### sim/

#### `sim/sensors.py`

- Line 95: `def render(self, robot_x: float, robot_y: float, robot_angle: float, walls: list):`
- Line 97: `Render first-person view from robot's perspective.`
- Line 110: `# Render walls with perspective`

#### `sim/world.py`

*20 references found. Showing first 5:*

- Line 40: `# Opaque surface in the current display format`
- Line 61: `pygame.display.set_caption("Rider-Pi 2D Simulator")`
- Line 70: `self.screen = pygame.display.set_mode((self.width, self.height))`
- Line 163: `"""Convert grid coordinates to screen coordinates."""`
- Line 177: `"""Render the main top-down view panel."""`


### tests/

#### `tests/acceptance_criteria.py`

- Line 57: `camera_surface = camera.render(robot.x, robot.y, robot.angle, world.wall_segments)`
- Line 58: `world.render(robot, camera_surface)`
- Line 101: `surface = camera.render(5.0, 5.0, 0.0, walls)`
- Line 103: `assert surface is not None, "Camera should render a surface"`

#### `tests/final_verification_sim3.py`

- Line 71: `# Render from different distances`
- Line 72: `surface_far = camera.render(2.0, 5.0, 0.0, walls)`
- Line 73: `surface_near = camera.render(4.5, 5.0, 0.0, walls)`
- Line 108: `camera_surface = camera.render(robot.x, robot.y, robot.angle, world.wall_segments)`
- Line 109: `world.render(robot, camera_surface)`
- Line 128: `# Render and publish camera`
- Line 129: `camera.render(5.0, 5.0, 0.0, [])`

#### `tests/screenshot_simulator.py`

- Line 41: `# Render a few frames to let things settle`
- Line 44: `camera_surface = camera.render(robot.x, robot.y, robot.angle, world.wall_segments)`
- Line 45: `world.render(robot, camera_surface)`
- Line 51: `pygame.image.save(world.screen, "sim_screenshot.png")`

#### `tests/test_blink_shift_coupling.py`

- Line 5: `from PIL import Image`

#### `tests/test_drivers_import.py`

- Line 27: `from drivers.lcd import PanelCfg`
- Line 42: `"""Test LCD driver factory function."""`
- Line 43: `from drivers.lcd import make_driver`

#### `tests/test_face_anim_api.py`

- Line 127: `"/face/render",`
- Line 163: `# Best-effort: w trakcie animacji w sys.modules nie powinno być sterowników LCD/SPI`

#### `tests/test_face_anim_nullsink.py`

- Line 65: `(mirror do PNG) — bez crashy i bez zależności od LCD/SPI.`

#### `tests/test_face_lcd_anim.py`

- Line 11: `@pytest.mark.skipif(os.environ.get("FACE_SINK") == "lcd", reason="Brak LCD w CI")`
- Line 29: `@pytest.mark.skipif(True, reason="Brak LCD w CI")`
- Line 31: `os.environ["FACE_SINK"] = "lcd"`
- Line 33: `r = requests.post(f"{API}/face/play", json={"expr": "happy", "fps": 10, "sink": "lcd"})`
- Line 38: `assert "LCD not available" in data["error"] or "LCD" in data["error"]`
- Line 42: `# /face/render`
- Line 43: `r = requests.post(f"{API}/face/render", json={"expr": "happy"}, headers={"Accept": "image/png"})`

#### `tests/test_face_render_pupil.py`

- Line 7: `from PIL import Image`

#### `tests/test_face_render_rotation.py`

- Line 7: `from PIL import Image`

#### `tests/test_look_moves_pupil.py`

- Line 5: `from PIL import Image`

#### `tests/test_no_underscore_apps_dependency.py`

- Line 14: `"scripts/dev_face-lcd-direct.py",`

#### `tests/test_pupil_clamp_and_blink.py`

- Line 5: `from PIL import Image`

#### `tests/test_pupil_drift.py`

- Line 5: `from PIL import Image`

#### `tests/test_renderer_basics.py`

- Line 2: `from PIL import Image`

#### `tests/test_sim3_acceptance.py`

*14 references found. Showing first 5:*

- Line 67: `# Render from robot position`
- Line 69: `surface = camera.render(robot_x, robot_y, robot_angle, walls)`
- Line 72: `assert surface is not None, "Camera should render a surface"`
- Line 86: `# Render from far away`
- Line 87: `surface_far = camera.render(2.0, 5.0, 0.0, walls)`

#### `tests/test_sim_screenshot.py`

- Line 25: `# Render a frame`
- Line 49: `world.render(dummy_robot, camera_surface)`
- Line 52: `pygame.image.save(world.screen, "sim_basic_screenshot.png")`

#### `tests/test_simulation_toggle.py`

- Line 89: `"""Test LCD driver returns simulated implementation when RIDER_SIMULATOR=1."""`
- Line 95: `import drivers.lcd`
- Line 97: `importlib.reload(drivers.lcd)`
- Line 98: `from drivers.lcd import get_lcd_driver`
- Line 105: `from drivers.lcd.sim import SimulatedLCDRenderer`
- Line 114: `# Note: We can't actually call ShowImage without PIL, but we can check it exists`
- Line 119: `from drivers.lcd.sim import SimulatedLCDDriver`

#### `tests/test_simulator_basic.py`

- Line 91: `world.render()`
- Line 110: `"""Test coordinate conversion from grid to screen."""`
- Line 116: `# Should return valid screen coordinates`

#### `tests/test_simulator_init.py`

- Line 3: `Headless test to verify simulator can initialize without display.`
- Line 12: `# Prevent pygame from requiring display`

#### `tests/test_sink_lcd_path.py`

- Line 6: `from PIL import Image`
- Line 20: `return "pil"`
- Line 35: `assert sink.push_pil(img) == "pil"`

#### `tests/verify_sim1_acceptance.py`

- Line 31: `assert world.screen is not None, "Pygame window should be created"`
- Line 80: `world.render()`

#### `tests/verify_simulator.py`

- Line 66: `test_surface = camera.render(5.0, 5.0, 0.0, [])`
- Line 67: `assert test_surface is not None, "Camera should render a surface"`


---

## GPIO and Sensors

**Files with GPIO and Sensors references**: 46

### apps/

#### `apps/camera/preview_lcd.py`

- Line 3: `Rider-Pi: podgląd kamery na 2" SPI LCD + (opcjonalnie) detekcja obiektów i publikacja na bus.`

#### `apps/hw/sink_lcd.py`

- Line 31: `import spidev`
- Line 38: `raise LcdNotAvailable(f"SPI init fail: {e}") from e`
- Line 73: `print(f"[sink_lcd] SPI init fail: {e}")`
- Line 89: `Szybka ścieżka: wysyła surowe dane RGB565 do LCD przez SPI.`
- Line 95: `print("[sink_lcd] RAW path unavailable: SPI not initialized, fallback to PIL.")`
- Line 96: `raise RuntimeError("SPI not initialized")`

#### `apps/motion/xgo_adapter.py`

- Line 9: `- Jednolite, bezpieczne API do ruchu/LED/baterii/IMU + parę udogodnień.`
- Line 27: `- imu() -> dict|None        # {"roll":..,"pitch":..,"yaw":..} lub None`

#### `apps/safety/estop.py`

- Line 14: `# GPIO (opcjonalnie): ustaw ESTOP_GPIO=17 (BCM). Aktywne niskim stanem.`
- Line 21: `import RPi.GPIO as GPIO`
- Line 23: `GPIO.setmode(GPIO.BCM)`
- Line 24: `GPIO.setup(GPIO_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP if _ACTIVE_LOW else GPIO.PUD_DOWN)`
- Line 34: `2) fizyczny przycisk na GPIO (jeśli skonfigurowany), LUB`
- Line 40: `val = GPIO.input(GPIO_PIN)`

#### `apps/ui/buttons.py`

- Line 57: `_log(f"GPIO not available ({e}); fallback to simulation. Set BUTTONS_SIM=1 to silence.")`
- Line 75: `_log(f"Buttons ready (GPIO): L={LEFT} R={RIGHT} OK={OK} BACK={BACK} hold={HOLD}s")`

#### `apps/ui/manager.py`

- Line 72: `# spróbuj ustawić jasność; jeśli padnie na _pwm → zrób autoinit GPIO`
- Line 102: `import RPi.GPIO as GPIO`
- Line 104: `GPIO.setwarnings(False)`
- Line 105: `GPIO.setmode(GPIO.BCM)`
- Line 106: `GPIO.setup(bl_pin, GPIO.OUT)`
- Line 107: `pwm = GPIO.PWM(bl_pin, freq)`
- Line 114: `log(f"xgo: GPIO PWM init (pin={bl_pin}, freq={freq} Hz)")`
- Line 117: `log(f"xgo: GPIO PWM init err: {e}")`


### drivers/

#### `drivers/lcd/__init__.py`

- Line 25: `def make_driver(kind: Literal["mock", "spi"], cfg: PanelCfg) -> Driver:`
- Line 30: `kind: Type of driver ("mock" or "spi")`
- Line 40: `elif kind == "spi":`
- Line 42: `from .spi import SpiFaceDriver`
- Line 46: `raise RuntimeError("SPI driver not available") from err`

#### `drivers/lcd/driver_ili9xx.py`

*61 references found. Showing first 5:*

- Line 144: `# SPI hz / mode`
- Line 145: `spi = getattr(self.device, "SPI", None)`
- Line 147: `if spi is not None:`
- Line 150: `spi.max_speed_hz = hz`
- Line 152: `if hasattr(spi, "mode"):`

#### `drivers/lcd/spi.py`

- Line 9: `raise NotImplementedError("SPI driver: push_png niezaimplementowane")`
- Line 12: `raise NotImplementedError("SPI driver: push_rgb565 niezaimplementowane")`

#### `drivers/xgo/adapter.py`

- Line 6: `- Jednolite, bezpieczne API do ruchu/LED/baterii/IMU + parę udogodnień.`
- Line 24: `- imu() -> dict|None        # {"roll":..,"pitch":..,"yaw":..} lub None`
- Line 147: `def imu(self) -> dict | None:`
- Line 162: `"""Ogólne imu(1/0) – tam gdzie brak rider_balance_*."""`
- Line 166: `fn = getattr(self._dog, "imu", None)`
- Line 173: `"""Włącza/wyłącza aktywny balans (preferuj rider_balance_roll, fallback imu)."""`
- Line 177: `self._call("imu", 1 if on else 0)`

#### `drivers/xgo/sim.py`

- Line 49: `"imu",`
- Line 64: `"""Enable/disable IMU balance."""`
- Line 142: `def imu(self) -> dict | None:`
- Line 143: `"""Return simulated IMU data (always level)."""`


### examples/

#### `examples/demo_driver_factory.py`

- Line 74: `# Check IMU`
- Line 75: `imu = robot.imu()`
- Line 76: `if imu:`
- Line 77: `LOG.info(f"IMU: roll={imu['roll']:.1f}° pitch={imu['pitch']:.1f}° yaw={imu['yaw']:.1f}°")`

#### `examples/demo_sim3_sensors.py`

- Line 55: `gyro = VirtualGyro(rate_hz=10.0)`
- Line 60: `# Simulate robot movement and sensor publishing`
- Line 61: `print("\n3. Simulating robot movement with sensor publishing...")`
- Line 74: `print("   Time    | Gyro Angle | Camera | Robot Position")`
- Line 83: `pre_gyro_time = gyro.last_pub`
- Line 86: `# Publish sensor data`
- Line 87: `gyro.publish(robot.angle)`
- Line 92: `gyro_published = gyro.last_pub > pre_gyro_time`
- Line 97: `last_gyro_time = gyro.last_pub`
- Line 128: `print("  [AC1] ✓ Gyroscope publishes robot orientation on rider.gyro.angle")`

#### `examples/navigate_simulator.py`

- Line 28: `# Create subscriber for gyro data`
- Line 29: `sub = BusSub("rider.gyro.angle")`
- Line 54: `print("\n=== Reading final orientation from gyro ===")`
- Line 55: `# Read one gyro message`
- Line 60: `print("No gyro data received (is simulator running?)")`


### scripts/

#### `scripts/demo_weather-lcd.py`

- Line 322: `p.add_argument("--spi-hz", type=int, default=None, help="Częstotliwość SPI")`

#### `scripts/dev/robot_dev.sh`

- Line 36: `robot_dev.sh takeover      # przejęcie ekranu: pkill root-start app + zwolnij SPI`

#### `scripts/dev_face-cli.py`

- Line 46: `parser = argparse.ArgumentParser(description="Face LCD CLI (mock/spi)")`
- Line 49: `parser.add_argument("--spi-hz", type=int, help="Częstotliwość SPI (opcjonalnie)")`
- Line 57: `parser.add_argument("--backend", choices=["mock", "spi"], help="Backend drivera (domyślnie mock lub ...`

#### `scripts/dev_face-lcd-clean.py`

- Line 87: `if hasattr(dev, "SPI") and spi_hz:`
- Line 88: `dev.SPI.max_speed_hz = spi_hz`

#### `scripts/dev_face-lcd-direct.py`

- Line 401: `"--spi-hz",`
- Line 404: `help="Prędkość SPI",`

#### `scripts/dev_face-presenter.py`

- Line 102: `spi = getattr(dev, "SPI", None)`
- Line 103: `if spi is not None:`
- Line 106: `spi.max_speed_hz = hz`
- Line 107: `if hasattr(spi, "mode"):`
- Line 108: `spi.mode = mode`

#### `scripts/dev_lcd-clear.py`

- Line 62: `# Ustaw tryb SPI (jeśli sterownik to wystawia)`
- Line 63: `spi = getattr(dev, "SPI", None)`
- Line 64: `if spi is not None:`
- Line 67: `spi.max_speed_hz = SPI_HZ`
- Line 68: `if hasattr(spi, "mode"):`
- Line 69: `spi.mode = SPI_MODE`

#### `scripts/dev_lcd-show-raw.py`

- Line 23: `# ustaw SPI mode jeśli mamy uchwyt`
- Line 24: `spi = getattr(d, "SPI", None)`
- Line 25: `if spi is not None and hasattr(spi, "mode"):`
- Line 27: `spi.mode = SPI_MODE`

#### `scripts/dev_lcd-testcard.py`

- Line 57: `spi = getattr(dev, "SPI", None)`
- Line 58: `if spi is not None:`
- Line 61: `spi.max_speed_hz = SPI_HZ`
- Line 62: `if hasattr(spi, "mode"):`
- Line 63: `spi.mode = SPI_MODE`

#### `scripts/dev_manual-drive.py`

- Line 20: `i           - pokaż IMU (roll/pitch/yaw)`
- Line 41: `imu = adapter.imu() or {}`
- Line 43: `return float(imu.get("yaw") or 0.0)`
- Line 88: `imu = ada.imu()`
- Line 89: `if imu is None:`
- Line 90: `print("[IMU] brak danych")`
- Line 92: `print(f"[IMU] roll={imu.get('roll'):.2f} pitch={imu.get('pitch'):.2f} yaw={imu.get('yaw'):.2f}")`

#### `scripts/dev_panel-nuke.py`

- Line 66: `print(f"OK: init COLMOD=0x{COLMOD:02X}, MADCTL=0x{MADCTL:02X}, SPI={SPIHZ or 'driver default'}; W={W...`

#### `scripts/dev_panel-reset-safe.py`

- Line 81: `ap.add_argument("--spi-hz", type=int, default=int(os.getenv("FACE_LCD_SPI_HZ", "0") or 0))`
- Line 101: `# ustaw SPI hz, jeśli jest`
- Line 103: `if args.spi_hz and hasattr(dev, "SPI"):`
- Line 104: `dev.SPI.max_speed_hz = args.spi_hz`
- Line 160: `spi_now = getattr(getattr(dev, "SPI", None), "max_speed_hz", 0) or 0`
- Line 165: `f"MADCTL=0x{int(str(args.madctl), 0):02X}, invert={args.invert}, SPI={spi_now or args.spi_hz})."`

#### `scripts/dev_panel-reset.py`

- Line 20: `# spróbuj ustawić SPI mode jeśli mamy uchwyt`
- Line 21: `spi = getattr(getattr(lcd, "device", None), "SPI", None)`
- Line 22: `if spi is not None and hasattr(spi, "mode"):`
- Line 24: `spi.mode = SPIMODE`
- Line 74: `f"... SPI={SPIHZ or getattr(spi, 'max_speed_hz', '-')} mode={getattr(spi, 'mode', '-')}",`

#### `scripts/diag_lcd-raw.py`

- Line 94: `# prędkość + tryb SPI (jeśli dostępne)`
- Line 95: `spi = getattr(dev, "SPI", None)`
- Line 96: `if spi is not None:`
- Line 99: `spi.max_speed_hz = SPIHZ`
- Line 100: `if hasattr(spi, "mode"):`
- Line 101: `spi.mode = SPIMODE`
- Line 102: `print(f"[diag] SPI set: hz={getattr(spi, 'max_speed_hz', None)} mode={getattr(spi, 'mode', None)}")`
- Line 104: `print("[diag] WARN spi params:", e)`

#### `scripts/sim/run_simulation.py`

- Line 56: `gyro = VirtualGyro(rate_hz=10.0)`
- Line 77: `# Publish sensor data`
- Line 78: `gyro.publish(robot.angle)`

#### `scripts/sys_boot-prepare.sh`

- Line 79: `if command -v raspi-gpio >/dev/null 2>&1; then`
- Line 81: `log "leaving LCD backlight ON (debug); forcing GPIO${LCD_BL_GPIO}=HIGH"`
- Line 82: `raspi-gpio set "${LCD_BL_GPIO}" op dh || true`
- Line 84: `log "turning LCD backlight off via raspi-gpio GPIO${LCD_BL_GPIO}"`
- Line 85: `raspi-gpio set "${LCD_BL_GPIO}" op dl || true`

#### `scripts/sys_camera-kill.sh`

- Line 2: `# camera_takeover_kill.sh — free camera/SPI and light up LCD backlight`
- Line 4: `# BL pin: GPIO 13 (active-high)`
- Line 11: `if command -v raspi-gpio >/dev/null 2>&1; then`
- Line 12: `raspi-gpio set 13 op dh || true`
- Line 36: `# 5) Force-close uchwytów do urządzeń: SPI i kamera`
- Line 43: `# (opcjonalnie) zwolnij uchwyty do GPIO chipów — nie szkodzi, gdy brak`

#### `scripts/sys_lcd-control.py`

*50 references found. Showing first 5:*

- Line 3: `Rider-Pi LCD controller (2" SPI TFT) — ON/OFF (+ status, optional no-spi mode)`
- Line 11: `sudo NO_SPI=1 python3 scripts/sys_lcd-control.py off # tylko podświetlenie (bez komend SPI)`
- Line 12: `sudo python3 scripts/sys_lcd-control.py off --no-spi # j.w.`
- Line 19: `--spi /dev/spidevX.Y (SPI_DEV)`
- Line 21: `--no-spi       (NO_SPI=1)    | nie wysyłaj komend SPI (BL only)`

#### `scripts/sys_splash-info.py`

- Line 60: `RASPI_GPIO_BIN = "raspi-gpio"`
- Line 552: `_log(f"BL GPIO{XGO_BL_GPIO}: {'LOW' if low else 'HIGH'}")`


### services/

#### `services/api_core/face_anim.py`

- Line 28: `# ====================== SINKI (bez wczesnego LCD/SPI) ========================`


### sim/

#### `sim/sensors.py`

- Line 22: `GYRO_TOPIC = os.getenv("GYRO_TOPIC", "rider.gyro.angle")`
- Line 45: `LOG.info(f"Gyro PUB → {BUS_PUB_ADDR} topic='{GYRO_TOPIC}' @ {self.rate_hz} Hz")`
- Line 47: `LOG.warning(f"Failed to initialize gyro MQTT: {e}")`
- Line 50: `"""Publish gyro angle if enough time has passed."""`
- Line 63: `LOG.debug(f"Error publishing gyro: {e}")`


### tests/

#### `tests/acceptance_criteria.py`

- Line 129: `# AC6: Symulator publikuje na rider/gyro/angle i rider/camera/frame`
- Line 130: `print("\n[AC6] Simulator publishes to MQTT topics (gyro/angle, camera/frame)")`
- Line 134: `gyro = VirtualGyro(rate_hz=10.0)`
- Line 138: `assert gyro._pub is not None, "Gyro should have MQTT publisher"`
- Line 142: `criteria.append(("AC6", True, "✓ Sensor publishers initialized (requires broker for full test)"))`

#### `tests/final_verification_sim3.py`

*11 references found. Showing first 5:*

- Line 41: `assert GYRO_TOPIC == "rider.gyro.angle", "Gyro topic must be rider.gyro.angle"`
- Line 42: `gyro = VirtualGyro(rate_hz=10.0)`
- Line 43: `assert gyro._pub is not None, "Gyro must have MQTT publisher"`
- Line 44: `gyro.publish(1.5708)  # 90 degrees in radians`
- Line 47: `check("1. Virtual Gyroscope publishes on rider.gyro.angle", test_gyro)`

#### `tests/test_face_anim_api.py`

- Line 163: `# Best-effort: w trakcie animacji w sys.modules nie powinno być sterowników LCD/SPI`
- Line 171: `if (k.startswith("apps.hw") or "sink_lcd" in k or "spi" in k)`

#### `tests/test_face_anim_nullsink.py`

- Line 65: `(mirror do PNG) — bez crashy i bez zależności od LCD/SPI.`

#### `tests/test_motion.py`

- Line 9: `- stop, IMU, bateria`
- Line 51: `print("IMU:", ada.imu())`

#### `tests/test_sim3_acceptance.py`

*12 references found. Showing first 5:*

- Line 6: `1. Gyro publishes robot orientation on rider.gyro.angle`
- Line 29: `"""AC1: Robot orientation is cyclically published on rider.gyro.angle."""`
- Line 32: `gyro = VirtualGyro(rate_hz=100.0)  # High rate for quick testing`
- Line 34: `# Verify gyro has MQTT publisher`
- Line 35: `assert gyro._pub is not None, "Gyro should have MQTT publisher initialized"`

#### `tests/test_simulation_toggle.py`

- Line 73: `# Test sensor methods`
- Line 79: `imu = driver.imu()`
- Line 80: `self.assertIsNotNone(imu)`
- Line 81: `self.assertIn("roll", imu)`
- Line 82: `self.assertIn("pitch", imu)`
- Line 83: `self.assertIn("yaw", imu)`

#### `tests/test_simulator_init.py`

- Line 34: `print("✓ Gyro initialized")`

#### `tests/test_simulator_integration.py`

- Line 42: `# Create subscriber for gyro data`
- Line 43: `sub = BusSub("rider.gyro.angle")`
- Line 56: `# Test 2: Receive gyro data`
- Line 57: `print("\n[Test 2] Receiving gyro data...")`
- Line 69: `print("✓ Gyro data received successfully")`
- Line 71: `print("✗ No gyro data received (simulator may not be running)")`

#### `tests/verify_hardware_isolation.py`

- Line 24: `re.compile(r"^\s*from\s+RPi\.GPIO\s+import"),`
- Line 25: `re.compile(r"^\s*import\s+RPi\.GPIO"),`
- Line 70: `"apps/safety",  # E-stop and safety checks may need direct GPIO access`
- Line 71: `"apps/ui/manager.py",  # UI manager may need GPIO for buttons`

#### `tests/verify_simulator.py`

- Line 59: `gyro = VirtualGyro(rate_hz=100.0)`


---

## MQTT and Messaging

**Files with MQTT and Messaging references**: 62

### apps/

#### `apps/camera/preview_lcd.py`

- Line 99: `print("[preview] pyzmq niedostępny (publish off):", e, file=sys.stderr)`
- Line 103: `def publish(topic: str, payload: dict, add_ts: bool = False):`
- Line 109: `PUB.publish(topic, payload)`
- Line 128: `publish("camera.heartbeat", payload, add_ts=True)`
- Line 426: `publish(`

#### `apps/camera/preview_lcd_hybrid.py`

- Line 26: `PUB.publish(topic, payload, add_ts=add_ts)`

#### `apps/camera/preview_lcd_ssd.py`

- Line 332: `PUB.publish(`

#### `apps/chat/main.py`

- Line 111: `PUB.publish("tts.speak", {"text": ans, "ts": now_ts(), "source": "chat"})`

#### `apps/choreographer/main.py`

- Line 91: `pub.publish(topic, payload, add_ts=True)`
- Line 94: `LOG.error(f"Failed to publish to {topic}: {e}")`
- Line 153: `# Collect all topics to subscribe to`
- Line 158: `# For wildcard topics, subscribe to the prefix`
- Line 165: `LOG.warning("No topics to subscribe to. Check configuration.")`
- Line 167: `topics_to_subscribe.add("events")  # Subscribe to base events topic`

#### `apps/main.py`

- Line 7: `- Szybkie testy drive/stop przez broker.`

#### `apps/menu/main.py`

- Line 36: `for m in ("send", "publish", "pub"):`

#### `apps/motion/main.py`

- Line 11: `- telemetria PUB 'motion.state' na broker (tcp://127.0.0.1:5555)`
- Line 140: `LOG.debug(f"Telemetry publish error: {e}")`
- Line 229: `self._sub.setsockopt(zmq.SUBSCRIBE, self.topic)`

#### `apps/nlu/main.py`

- Line 62: `for m in ("send", "publish", "pub"):`
- Line 65: `raise AttributeError("BusPub bez send/publish/pub")`

#### `apps/ui/buttons.py`

- Line 29: `"""Wyślij przez BusPub niezależnie od nazwy metody (send/publish/pub)."""`
- Line 30: `for m in ("send", "publish", "pub"):`
- Line 33: `raise AttributeError("BusPub has no send/publish/pub method")`

#### `apps/ui/manager.py`

- Line 218: `s.setsockopt(zmq.SUBSCRIBE, MOTION_T)`
- Line 219: `s.setsockopt(zmq.SUBSCRIBE, VISION_T)`

#### `apps/ui/overlay.py`

- Line 26: `s.setsockopt(zmq.SUBSCRIBE, t)`

#### `apps/vision/detector_hog.py`

- Line 96: `PUB.publish(`

#### `apps/vision/detector_tflite.py`

- Line 40: `s.setsockopt_string(zmq.SUBSCRIBE, t)`

#### `apps/vision/dispatcher.py`

- Line 54: `s.setsockopt_string(zmq.SUBSCRIBE, t)`

#### `apps/vision/obstacle_roi.py`

- Line 68: `PUBLISH = _env_int("PUBLISH", 0)`
- Line 225: `if PUBLISH:`
- Line 236: `def publish(topic: str, payload: dict[str, Any]) -> None:`
- Line 291: `publish("vision.obstacle", payload)`

#### `apps/voice/stream/handlers.py`

- Line 247: `self.ui_publisher.publish("ui.state", {"state": state, "ts": time.time()})`
- Line 255: `self.ui_publisher.publish("ui.partial", {"text": text, "ts": time.time()})`
- Line 262: `self.ui_publisher.publish("ui.error", {"type": error_type, "message": message, "ts": time.time()})`
- Line 537: `pub.publish("ui.state", {"state": "hearing"})`
- Line 547: `pub.publish("ui.partial", {"text": data.get("delta", "")})`

#### `apps/voice/stream/svc_streaming.py`

- Line 141: `if pub and hasattr(pub, "publish"):`
- Line 143: `pub.publish("ui.error", payload)`
- Line 342: `# UI publish (delegated to StreamHandlersMixin)`

#### `apps/voice/svc_bus.py`

- Line 46: `self._bus_pub.publish("ui.state", {"state": state}, add_ts=True)`
- Line 61: `self._bus_pub.publish("audio.transcript", payload, add_ts=True)`
- Line 69: `self._bus_pub.publish("assistant.speech", {"text": text}, add_ts=True)`
- Line 77: `"""Subscribe to tts.speak bus topic and queue speech tasks."""`


### common/

#### `common/bus.py`

- Line 11: `# Broker endpoints (możesz nadpisać ENV-em; zostawiamy wartości domyślne)`
- Line 23: `Kompatybilny wstecz z poprzednią wersją (publish(topic, payload)).`
- Line 40: `def publish(self, topic: str, payload: dict, add_ts: bool = False) -> None:`
- Line 53: `self.publish(topic, payload)`
- Line 84: `self.subscribe(t)`
- Line 86: `def subscribe(self, topic: str) -> None:`
- Line 88: `self.sock.setsockopt(zmq.SUBSCRIBE, topic.encode("utf-8"))`

#### `common/cam_heartbeat.py`

- Line 41: `self.pub.publish(`


### examples/

#### `examples/demo_sim3_sensors.py`

- Line 6: `data to MQTT topics. It shows what data is being published and verifies`
- Line 10: `# Terminal 1: Start broker`
- Line 11: `python services/broker.py`
- Line 62: `print("   Publishing to MQTT (requires broker at tcp://127.0.0.1:5555)")`
- Line 86: `# Publish sensor data`
- Line 87: `gyro.publish(robot.angle)`
- Line 89: `camera.publish()`
- Line 133: `print("To verify MQTT messages are actually sent:")`
- Line 134: `print("  1. Start broker: python services/broker.py")`

#### `examples/navigate_simulator.py`

- Line 5: `This demonstrates how to control the simulated robot via MQTT.`
- Line 21: `print("Make sure the broker and simulator are running:\n")`
- Line 22: `print("  Terminal 1: python services/broker.py")`
- Line 34: `pub.publish("motion", {"type": "drive", "lx": 0.3, "az": 0.0})`
- Line 40: `pub.publish("motion", {"type": "drive", "lx": 0.0, "az": 0.4})`
- Line 51: `pub.publish("motion", {"type": "stop"})`
- Line 75: `print("\nMake sure broker and simulator are running!")`


### scripts/

#### `scripts/demo/choreographer_demo.py`

- Line 34: `"""Publish sample sentiment events to demonstrate choreography."""`
- Line 56: `pub.publish("events.sentiment", payload, add_ts=True)`
- Line 87: `# Subscribe to all command topics and motion`
- Line 111: `choices=["publish", "listen"],`
- Line 112: `help="publish: send test events; listen: monitor commands",`
- Line 117: `if args.mode == "publish":`

#### `scripts/demo/streaming.py`

- Line 119: `def publish(self, topic, payload):`

#### `scripts/dev/robot_dev.sh`

- Line 2: `# robot_dev.sh — dev launcher (broker | voice | chat | face | nlu | tts2face | all | restart | stop ...`
- Line 30: `robot_dev.sh broker        # uruchom broker (FG)`
- Line 37: `robot_dev.sh all           # broker + voice + (chat gdy VOICE_STANDALONE=0) + face`
- Line 63: `say "start: broker"`
- Line 65: `python3 services/broker.py`
- Line 105: `"services/broker.py" \`
- Line 128: `"services/broker.py"`
- Line 157: `run_bg broker   "env BUS_HOST='$BUS_HOST' BUS_PUB='$BUS_PUB' BUS_SUB='$BUS_SUB' python3 services/bro...`
- Line 169: `broker)     start_broker ;;`

#### `scripts/dev_bus-dump.py`

- Line 30: `sub.setsockopt(zmq.SUBSCRIBE, b"")`
- Line 33: `sub.setsockopt(zmq.SUBSCRIBE, TOPIC.encode("utf-8"))`

#### `scripts/dev_bus-state.py`

- Line 15: `sub.setsockopt(zmq.SUBSCRIBE, TOPIC)`

#### `scripts/diag_bus-spy.py`

- Line 14: `s.setsockopt_string(zmq.SUBSCRIBE, t)`

#### `scripts/diag_test-suite.sh`

- Line 9: `LOG_BROKER="/tmp/broker.log"`
- Line 21: `pkill -f services/broker.py || true`
- Line 25: `say "Start broker"`
- Line 26: `nohup python3 services/broker.py >> "$LOG_BROKER" 2>&1 &`
- Line 73: `echo "--- broker ---"; tail -n 20 "$LOG_BROKER" || true`

#### `scripts/diagnose_services.sh`

- Line 13: `NAMES_ORDER=(broker web motion cam edge ssd obstacle api)  # api NA KOŃCU i TYLKO STATUS!`
- Line 149: `broker|web)`

#### `scripts/sim/demo_simulator.sh`

- Line 17: `# Start broker in background`
- Line 18: `echo "[2/5] Starting ZMQ broker..."`
- Line 19: `python3 services/broker.py &`
- Line 22: `echo "  ✓ Broker running (PID: $BROKER_PID)"`
- Line 82: `echo "  Terminal 1: python services/broker.py"`

#### `scripts/sim/run_simulation.py`

- Line 6: `Communicates with the motion control system via MQTT bus.`
- Line 77: `# Publish sensor data`
- Line 78: `gyro.publish(robot.angle)`
- Line 82: `camera.publish()`

#### `scripts/sys_cleanup.sh`

- Line 91: `systemctl show -p ExecStart -p FragmentPath rider-broker.service 2>/dev/null | sed 's/; /\n/g' || tr...`

#### `scripts/sys_control.sh`

- Line 7: `rider-broker.service`

#### `scripts/sys_emergency-stop.py`

- Line 5: `E-Stop ON/OFF/STATUS przez plik-flagę, plus natychmiastowy STOP przez broker.`

#### `scripts/systemd-sync.sh`

- Line 16: `"rider-broker.service"`


### services/

#### `services/api_core/compat.py`

- Line 173: `# ── Bus publish (opcjonalny) ─────────────────────────────────────────────────`
- Line 483: `"broker": "unknown",`

#### `services/api_core/device_status.py`

- Line 47: `return {"broker": "unknown", "last_seen_ts": None}`

#### `services/api_core/devices.py`

- Line 95: `sub.setsockopt_string(zmq.SUBSCRIBE, t)`

#### `services/api_core/services_api.py`

- Line 17: `"broker": "rider-broker.service",`

#### `services/broker.py`

- Line 5: `ZeroMQ broker XSUB↔XPUB`
- Line 17: `LOG = logging.getLogger("broker")`
- Line 28: `# (opcjonalnie) pokaż SUBSCRIBE/UNSUB na XPUB:`
- Line 34: `LOG.info(f"Broker XSUB {FRONT_ADDR}  <->  XPUB {BACK_ADDR}")`
- Line 49: `LOG.info("Broker: shutting down")`

#### `services/motion_bridge.py`

- Line 194: `sub.setsockopt_string(zmq.SUBSCRIBE, t)`

#### `services/motion_cmd_shim.py`

- Line 13: `# SUB: legacy od dashboardu (broker SUB:5556)`
- Line 16: `sub.setsockopt_string(zmq.SUBSCRIBE, "motion.cmd")`
- Line 18: `# PUB: nowe komendy do bridge (broker PUB:5555)`

#### `services/web_motion_bridge.py`

- Line 32: `# jeżeli chcesz uruchamiać ten mostek jako broker PUB — ustaw WEB_BIND_PUB=1`


### sim/

#### `sim/robot.py`

- Line 3: `Simulated Robot - Virtual robot model with MQTT control integration`
- Line 17: `# MQTT configuration`
- Line 24: `Virtual robot that receives control commands via MQTT and simulates physics.`
- Line 34: `# MQTT setup`
- Line 41: `"""Initialize MQTT subscriber for control commands."""`
- Line 46: `self._sub.setsockopt(zmq.SUBSCRIBE, CONTROL_TOPIC.encode("utf-8"))`
- Line 51: `LOG.warning(f"Failed to initialize MQTT: {e}")`
- Line 54: `"""Receive and process control commands from MQTT."""`

#### `sim/sensors.py`

- Line 3: `Virtual Sensors - Simulated gyroscope and camera with MQTT publishing`
- Line 20: `# MQTT configuration`
- Line 39: `"""Initialize MQTT publisher."""`
- Line 47: `LOG.warning(f"Failed to initialize gyro MQTT: {e}")`
- Line 49: `def publish(self, angle: float):`
- Line 50: `"""Publish gyro angle if enough time has passed."""`
- Line 93: `LOG.warning(f"Failed to initialize camera MQTT: {e}")`
- Line 172: `def publish(self):`
- Line 173: `"""Publish camera frame if enough time has passed."""`
- Line 189: `# Publish as binary data`

#### `sim/world.py`

- Line 289: `"Control via MQTT:",`


### tests/

#### `tests/acceptance_criteria.py`

- Line 65: `# AC3: Wysłanie wiadomości MQTT powoduje ruch robota`
- Line 66: `print("\n[AC3] MQTT message on 'motion' topic causes robot movement")`
- Line 84: `criteria.append(("AC3", True, "✓ MQTT commands control robot movement"))`
- Line 130: `print("\n[AC6] Simulator publishes to MQTT topics (gyro/angle, camera/frame)")`
- Line 138: `assert gyro._pub is not None, "Gyro should have MQTT publisher"`
- Line 139: `assert camera._pub is not None, "Camera should have MQTT publisher"`
- Line 141: `# Note: Actual MQTT publishing requires broker running`
- Line 142: `criteria.append(("AC6", True, "✓ Sensor publishers initialized (requires broker for full test)"))`

#### `tests/diag_snapshot.sh`

- Line 31: `SERVICES=(rider-broker.service rider-web-bridge.service rider-motion-bridge.service rider-api.servic...`

#### `tests/final_verification_sim3.py`

- Line 43: `assert gyro._pub is not None, "Gyro must have MQTT publisher"`
- Line 44: `gyro.publish(1.5708)  # 90 degrees in radians`
- Line 58: `assert camera._pub is not None, "Camera must have MQTT publisher"`
- Line 117: `# Test 6: MQTT Publishing`
- Line 124: `# Publish gyro`
- Line 125: `gyro.publish(1.0)`
- Line 128: `# Render and publish camera`
- Line 130: `camera.publish()`
- Line 134: `check("6. MQTT publishing works for both sensors", test_mqtt_publishing)`
- Line 162: `check("8. MQTT topics and addresses correctly configured", test_configuration)`

#### `tests/reboot_safety_check.sh`

- Line 21: `NEEDED=(rider-broker.service rider-motion-bridge.service rider-web-bridge.service rider-api.service)`
- Line 30: `systemd-analyze verify "$ROOT/systemd"/rider-{broker,motion-bridge,web-bridge,api}.service || die "v...`
- Line 34: `sudo systemctl restart rider-broker.service`

#### `tests/test_choreographer_integration.py`

- Line 31: `assert pub.publish.call_count >= 1`
- Line 34: `topics_called = [call[0][0] for call in pub.publish.call_args_list]`
- Line 57: `assert pub.publish.call_count == 1`
- Line 58: `assert pub.publish.call_args[0][0] == "command.test.a"`
- Line 65: `assert pub.publish.call_args[0][0] == "command.test.b"`
- Line 83: `pub.publish.assert_not_called()`
- Line 114: `pub.publish.assert_called_once()`
- Line 115: `call_kwargs = pub.publish.call_args[1]`
- Line 147: `# Action with topic but pub.publish raises exception`
- Line 148: `pub.publish.side_effect = Exception("Test error")`

#### `tests/test_choreographer_mapping.py`

- Line 99: `pub.publish.assert_not_called()`
- Line 120: `pub.publish.assert_called_once()`
- Line 121: `call_args = pub.publish.call_args`
- Line 146: `assert pub.publish.call_count == 2`
- Line 165: `assert pub.publish.call_count == 1`
- Line 188: `# Should not publish`

#### `tests/test_motion_bus.py`

- Line 36: `sub.setsockopt_string(zmq.SUBSCRIBE, ECHO_TOPIC)`

#### `tests/test_sim3_acceptance.py`

*13 references found. Showing first 5:*

- Line 34: `# Verify gyro has MQTT publisher`
- Line 35: `assert gyro._pub is not None, "Gyro should have MQTT publisher initialized"`
- Line 37: `# Verify publish method exists and can be called`
- Line 39: `gyro.publish(angle)  # Should not raise exception`
- Line 42: `gyro.publish(angle)`

#### `tests/test_simulator_integration.py`

*21 references found. Showing first 5:*

- Line 3: `Integration test for the simulator with MQTT bus`
- Line 4: `This test requires starting the broker and simulator separately`
- Line 25: `Manual integration test for simulator MQTT communication.`
- Line 27: `Run this test with the broker and simulator already running:`
- Line 29: `Terminal 1: python services/broker.py`

#### `tests/test_simulator_mqtt.py`

- Line 3: `Integration test for simulator with MQTT control.`
- Line 6: `1. Broker starts and proxies messages`
- Line 34: `"""Test MQTT integration with robot."""`
- Line 35: `print("Starting MQTT integration test...")`
- Line 37: `# Start broker as subprocess`
- Line 38: `print("Starting ZMQ broker...")`
- Line 40: `[sys.executable, "services/broker.py"],`
- Line 45: `# Wait for broker to start`
- Line 100: `print("\n✓ All MQTT integration tests passed!")`

#### `tests/test_simulator_robot.py`

- Line 3: `Test simulated robot physics and MQTT integration.`

#### `tests/test_voice_service_ui_state.py`

- Line 59: `def publish(self, topic: str, payload: dict, add_ts: bool = False) -> None:  # noqa: ARG002`
- Line 63: `self.publish(topic, payload)`

#### `tests/test_voice_streaming.py`

- Line 61: `def publish(topic: str, payload: dict):`
- Line 64: `publisher.publish = publish`
- Line 186: `assert len(mock_ui_publisher.messages) == 1  # Should not publish duplicate`
- Line 193: `# Test partial publish`

#### `tests/verify_simulator.py`

- Line 82: `print("  1. Start the broker: python services/broker.py")`


---

## State Management

**Files with State Management references**: 88

### apps/

#### `apps/camera/cam_motion.py`

- Line 197: `state = {`
- Line 205: `pub(pubsock, state)`

#### `apps/draw/face_primitives.py`

- Line 185: `}.get(getattr(model, "state", "idle"), 0.06)`
- Line 271: `if getattr(model, "assist_speaking", False) or getattr(model, "state", "") == "speak":`

#### `apps/google_bridge/puller.py`

*12 references found. Showing first 5:*

- Line 5: `This worker runs independently and writes status and data snapshots to local files.`
- Line 42: `STATUS_FILE = GOOGLE_DATA_DIR / "status.json"`
- Line 56: `def write_status(state: str, timestamp: float, errors_24h: int = 0, requests_24h: int = 0) -> None:`
- Line 57: `"""Write status to status.json file.`
- Line 60: `state: One of: enabled, ok, error, off`

#### `apps/main.py`

- Line 104: `print(f"[STATUS] motion_enable_flag={m}  estop_flag={e}  PUB_ADDR={PUB_ADDR}  TOPIC={TOPIC}")`
- Line 116: `print("7) Show status")`

#### `apps/menu/main.py`

*17 references found. Showing first 5:*

- Line 6: `Sub: ui.button, motion.state`
- Line 7: `Pub: system.mode, motion.cmd(stop), system.menu.state`
- Line 22: `SUB_MS = BusSub("motion.state")`
- Line 27: `state = {`
- Line 47: `"system.menu.state",`

#### `apps/motion/main.py`

- Line 11: `- telemetria PUB 'motion.state' na broker (tcp://127.0.0.1:5555)`
- Line 43: `STATE_TOPIC = os.getenv("MOTION_STATE_TOPIC", "motion.state")`
- Line 129: `def maybe_publish(self, state: dict):`
- Line 137: `payload = json.dumps(state, ensure_ascii=False).encode("utf-8")`
- Line 295: `state = {`
- Line 308: `telem.maybe_publish(state)`

#### `apps/ui/face/animator.py`

- Line 47: `self.state = FaceState()`
- Line 67: `node = self.state`
- Line 110: `return self.state`

#### `apps/ui/face/controller.py`

- Line 88: `self.anim.state.mouth.shape = init_shape`
- Line 91: `expr = getattr(self.anim.state, "expr", "neutral")`
- Line 93: `self.anim.state.mouth.shape = start`
- Line 114: `self.anim.state.expr = str(expr or "neutral")`
- Line 171: `st = self.anim.state`
- Line 235: `self.anim.state.mouth.shape = shape`

#### `apps/ui/face/model.py`

- Line 43: `# --- state dataclasses --------------------------------------------------------`

#### `apps/ui/manager.py`

- Line 19: `MOTION_T = os.getenv("MOTION_STATE_TOPIC", "motion.state").encode()`
- Line 20: `VISION_T = os.getenv("VISION_TOPIC", "vision.state").encode()`
- Line 162: `state = 1 if on else 0`
- Line 163: `if self._power == state:`
- Line 182: `ok = self._run(["/usr/bin/vcgencmd", "display_power", str(state)])`
- Line 191: `self._power = state`

#### `apps/ui/overlay.py`

- Line 15: `MOTION_T = os.getenv("MOTION_STATE_TOPIC", "motion.state").encode()`
- Line 16: `VISION_T = os.getenv("VISION_TOPIC", "vision.state").encode()`
- Line 39: `state = {"motion": {}, "vision": {}}`
- Line 56: `state["motion"] = json.loads(payload.decode("utf-8"))`
- Line 58: `state["vision"] = json.loads(payload.decode("utf-8"))`
- Line 63: `m = state.get("motion", {})`
- Line 64: `v = state.get("vision", {})`

#### `apps/vision/detector_tflite.py`

*17 references found. Showing first 5:*

- Line 9: `Topics OUT: vision.state, autonomy.perception (opcjonalnie), ui.face (opcjonalnie)`
- Line 73: `STATE = PresenceState()`
- Line 92: `global STATE`
- Line 95: `STATE.consecutive_pos += 1`
- Line 96: `STATE.last_pos_ts = now`

#### `apps/vision/dispatcher.py`

*18 references found. Showing first 5:*

- Line 9: `OUT: vision.state, vision.dispatcher.heartbeat`
- Line 105: `STATE = PresenceState()`
- Line 171: `"present": STATE.present,`
- Line 172: `"confidence": round(STATE.confidence, 3),`
- Line 176: `pub("vision.state", payload)`

#### `apps/vision/obstacle_roi.py`

- Line 9: `- (NOWE) Opcjonalne annotacje obrazu na PROC: kolorowy ROI + status + słabe-kolumny.`

#### `apps/voice/asr.py`

- Line 335: `logger.event("asr.local.http_error", status=resp.status_code, body=snippet)`

#### `apps/voice/chat.py`

- Line 299: `self._evt("chat.local.http_error", status=resp.status_code, body=snippet)`

#### `apps/voice/service.py`

- Line 72: `_log_info("voice.init", "env.state", data)`

#### `apps/voice/stream/handlers.py`

*22 references found. Showing first 5:*

- Line 5: `- PTT state callbacks`
- Line 8: `- UI state publishing`
- Line 26: `from .state import PTTEvent, PTTStateMachine`
- Line 66: `# PTT state callbacks`
- Line 69: `"""Setup PTT state machine callbacks."""`

#### `apps/voice/stream/playout.py`

- Line 99: `from .state import PTTEvent`
- Line 122: `self.ptt_state.transition(PTTEvent.TTS_START)`

#### `apps/voice/stream/state.py`

*48 references found. Showing first 5:*

- Line 1: `"""PTT (Push-to-Talk) state machine for Rider-Pi voice assistant.`
- Line 3: `Implements a clean state machine for voice interaction flows:`
- Line 17: `"""PTT state machine states."""`
- Line 26: `ERROR = auto()  # Error state`
- Line 30: `"""PTT state machine events."""`

#### `apps/voice/stream/svc_streaming.py`

- Line 2: `"""Refactored streaming voice service using transport and state modules.`
- Line 5: `focusing on orchestration while delegating transport and state management.`
- Line 34: `from .state import PTTEvent, PTTStateMachine`
- Line 162: `# State machine`
- Line 179: `# Session state`
- Line 337: `"""Async helper to transition from CLOSING to IDLE."""`
- Line 339: `self.ptt_state.transition(PTTEvent.TIMEOUT)`
- Line 364: `self.ptt_state.transition(PTTEvent.START)`

#### `apps/voice/stream/transport.py`

- Line 68: `# Connection state`
- Line 193: `await asyncio.to_thread(self.websocket.close, status=1000)`

#### `apps/voice/svc_bus.py`

- Line 2: `"""Bus integration for voice service (UI state publishing and TTS speak subscription)."""`
- Line 39: `def _publish_ui_state(self, state: str) -> None:`
- Line 40: `if state == self._last_ui_state:`
- Line 42: `self._last_ui_state = state`
- Line 46: `self._bus_pub.publish("ui.state", {"state": state}, add_ts=True)`
- Line 48: `self.logger.event("service.bus.state_failed", state=state, error=str(exc))`

#### `apps/voice/svc_file.py`

- Line 228: `# UI state cache`

#### `apps/voice/tts.py`

- Line 382: `"status": resp.status_code,`
- Line 614: `logger.event("tts.local.http_error", status=resp.status_code, body=snippet)`

#### `apps/voice/web.py`

- Line 528: `return jsonify({"status": "error", "error": "missing text"}), 400`
- Line 535: `return jsonify({"status": "error", "error": "piper module not available"}), 500`
- Line 544: `return jsonify({"status": "error", "error": f"local piper failed: {e}"}), 500`
- Line 547: `return jsonify({"status": "error", "error": "piper produced no WAV"}), 500`
- Line 551: `return jsonify({"status": "ok", "fmt": "wav", "audio_b64": b64})`
- Line 593: `return jsonify({"status": "error", "error": "synthesis produced no WAV"}), 500`
- Line 606: `return jsonify({"status": "error", "error": str(e)}), 500`


### config/

#### `config/alsa/preflight.sh`

- Line 319: `# Run main and exit with its status`


### examples/

#### `examples/demo_sim3_sensors.py`

- Line 103: `# Print status every 15 frames (0.5 seconds)`


### scripts/

#### `scripts/demo/streaming.py`

- Line 103: `print(f"   Current state: {service.current_state}")`
- Line 135: `# Test state transitions`

#### `scripts/dev/robot_dev.sh`

- Line 2: `# robot_dev.sh — dev launcher (broker | voice | chat | face | nlu | tts2face | all | restart | stop ...`
- Line 40: `robot_dev.sh status        # porty i procesy`
- Line 101: `# --- status/stop ---`
- Line 102: `status () {`
- Line 164: `say "all: done (sprawdź ./robot_dev.sh status)"`
- Line 179: `status)     status ; exit 0 ;;`

#### `scripts/dev_bus-pub.py`

- Line 14: `python3 scripts/dev_bus-pub.py motion.state '{"stopped": true, "last_cmd_age_ms": 1500}'`
- Line 15: `python3 scripts/dev_bus-pub.py vision.state '{"moving": false, "human": true}'`

#### `scripts/dev_bus-state.py`

- Line 10: `TOPIC = os.getenv("MOTION_STATE_TOPIC", "motion.state").encode()`
- Line 17: `print(f"[STATE] SUB {ADDR} topic='{TOPIC.decode()}'")`

#### `scripts/dev_check-legacy-imports.py`

- Line 13: `- apps/voice/state.py (removed in PR-3, use apps.voice.stream.state)`
- Line 47: `# Files removed in PR-3 (audio/state modules)`
- Line 58: `r"from apps\.voice\.state\b",`
- Line 59: `"apps/voice/state.py (removed in PR-3, use apps.voice.stream.state)",`
- Line 63: `"apps/voice/ptt_state.py (removed in PR-3, use apps.voice.stream.state)",`
- Line 66: `(r"import apps\.voice\.state\b", "apps/voice/state.py (removed in PR-3)"),`

#### `scripts/diag_bench-detect.sh`

- Line 26: `local status=0`
- Line 28: `out="$(timeout "${DUR}"s "${cmd[@]}" 2>&1 || status=$?)"`

#### `scripts/diag_sensors.py`

- Line 47: `for name in ("set_mode", "set_state", "mode", "state"):`

#### `scripts/diagnose_services.sh`

- Line 13: `NAMES_ORDER=(broker web motion cam edge ssd obstacle api)  # api NA KOŃCU i TYLKO STATUS!`
- Line 83: `active="$(echo "$json" | ${JQ_BIN} -r '.active // .status.active // empty')"`
- Line 84: `enabled="$(echo "$json" | ${JQ_BIN} -r '.enabled // .status.enabled // empty')"`
- Line 85: `sub="$(echo "$json"   | ${JQ_BIN} -r '.sub // .status.sub // empty')"`
- Line 104: `# STATUS`
- Line 109: `echo "  ${C_WARN}WARN:${C_OFF} status niedostępny (GET /svc/${name} i fallback z /svc)"`
- Line 113: `# Dla api: tylko status, bez akcji`
- Line 167: `# STATUS po operacjach`

#### `scripts/sys_emergency-stop.py`

- Line 5: `E-Stop ON/OFF/STATUS przez plik-flagę, plus natychmiastowy STOP przez broker.`
- Line 9: `python3 scripts/sys_emergency-stop.py status`
- Line 41: `if len(sys.argv) < 2 or sys.argv[1] not in {"on", "off", "status"}:`
- Line 42: `print("Usage: estop.py on|off|status")`

#### `scripts/sys_lcd-control.py`

- Line 3: `Rider-Pi LCD controller (2" SPI TFT) — ON/OFF (+ status, optional no-spi mode)`
- Line 10: `sudo python3 scripts/sys_lcd-control.py status       # szybka diagnostyka`
- Line 178: `print(f"[lcdctl] WARN: cannot read BL GPIO state: {e}")`
- Line 223: `sp_stat = sub.add_parser("status", help="diagnose current setup")`

#### `scripts/sys_led-control.py`

- Line 112: `def status(brightness: pathlib.Path, trigger: pathlib.Path, name: str) -> None:`
- Line 168: `sub.add_parser("status", help="pokaż stan LED-a")`
- Line 211: `if args.cmd == "status":`
- Line 212: `status(brightness, trigger, name)`

#### `scripts/sys_splash-info.sh`

- Line 22: `# Logo zostanie obrócone wg SPLASH_ROTATE i pokazane tym samym prezenterem co status.`
- Line 23: `# Błędy w tym kroku są ignorowane (kontynuujemy do status splash).`
- Line 41: `# PIL (Pillow) jest używany także w status splash, więc zakładamy, że jest dostępny.`
- Line 56: `# Nie udało się – trudno, wychodzimy po cichu (wrapper przejdzie dalej do status splash).`
- Line 68: `# Ignoruj problemy z LCD – przejdziemy do status splash`

#### `scripts/sys_vision-control.sh`

- Line 3: `# Zarządzanie usługą vision: on/off/burst/status`
- Line 32: `status)`
- Line 33: `systemctl --no-pager -l status "$SERVICE"`
- Line 36: `echo "Usage: $0 {on|off|burst [secs]|status}"`

#### `scripts/sys_voice-stream.sh`

- Line 79: `from apps.voice.stream.state import PTTEvent`
- Line 119: `service.ptt_state.transition(PTTEvent.START)`
- Line 138: `STATUS=$?`
- Line 139: `if [ ${STATUS} -eq 0 ]; then`
- Line 142: `echo "[voice.ops] Realtime chat demo failed with status ${STATUS}." >&2`
- Line 145: `exit ${STATUS}`

#### `scripts/sys_xgo-init.py`

- Line 86: `for name in ("set_mode", "set_state", "mode", "state"):`


### services/

#### `services/api_core/camera.py`

- Line 69: `def _json_error(name: str, status: int = 404) -> Response:`
- Line 72: `resp = make_response(body, status)`

#### `services/api_core/chat_glue.py`

- Line 87: `if resp.status >= 400:`
- Line 88: `return False, f"remote_http_{resp.status}"`

#### `services/api_core/compat.py`

*20 references found. Showing first 5:*

- Line 6: `- endpointy: /healthz, /health, /livez, /readyz, /state, /sysinfo, /metrics, /events`
- Line 7: `- aliasy /api/*: /api/status, /api/metrics (JSON), /api/devices, /api/last_frame, /api/flags`
- Line 255: `status = "ok"`
- Line 258: `status = "degraded"`
- Line 261: `"status": status,`

#### `services/api_core/control_api.py`

- Line 42: `return Response('{"error":"JSON object expected"}', mimetype="application/json", status=400)`
- Line 65: `return Response(json.dumps({"error": str(e)}), mimetype="application/json", status=500)`
- Line 92: `return Response('{"ok": false, "error": "unknown action"}', mimetype="application/json", status=400)`

#### `services/api_core/control_proxy.py`

- Line 58: `code = resp.status`

#### `services/api_core/dashboard.py`

- Line 14: `"<h1>Rider-Pi API</h1><p>Brak web/view.html – użyj <a href='/state'>/state</a>, "`

#### `services/api_core/devices.py`

- Line 204: `if topic == "vision.state":`

#### `services/api_core/face_anim.py`

*17 references found. Showing first 5:*

- Line 88: `STATE: dict[str, Any] = {`
- Line 133: `STATE["running"] = True`
- Line 134: `STATE["started_ts"] = time.time()`
- Line 135: `STATE["frame_count"] = 0`
- Line 138: `while not self._stop.is_set() and STATE.get("playing", False):`

#### `services/api_core/face_api.py`

- Line 60: `for name in ("FaceState", "State", "FaceCtx", "Face"):`
- Line 82: `state = _make_state(expr)`
- Line 84: `png = r.render_png_bytes(state)  # -> bytes`
- Line 144: `return r.render_image(state=state)  # PIL.Image`
- Line 170: `- błąd:   {"ok": false, "error": "...", "status": 503?}`
- Line 219: `return {"ok": False, "error": f"lcd-error: {e}", "status": 503}`
- Line 245: `Zwraca: (body: dict, status: int)`
- Line 255: `status = 503 if (not res.get("ok") and res.get("status") == 503) else 200`
- Line 256: `return res, status`

#### `services/api_core/google_proxy.py`

*11 references found. Showing first 5:*

- Line 5: `Provides endpoints to read status and data snapshots from the local Google feed cache.`
- Line 23: `STATUS_FILE = GOOGLE_DATA_DIR / "status.json"`
- Line 53: `@google_proxy.route("/status", methods=["GET"])`
- Line 55: `"""Get Google feed status.`
- Line 58: `JSON response with status information:`

#### `services/api_core/services_api.py`

- Line 54: `def _json(payload: Any, status: int = 200) -> Response:`
- Line 58: `status=status,`
- Line 221: `return _json({"error": "unknown service", "name": name}, status=404)`
- Line 234: `return _json({"error": "bad action", "allowed": list(ALLOWED_ACTIONS)}, status=400)`
- Line 246: `status=409,`
- Line 256: `# końcowy status celu`
- Line 268: `"status": status_obj,`
- Line 270: `return _json(payload, status=(200 if ok else 500))`

#### `services/api_core/state_api.py`

- Line 13: `def state() -> Response:`
- Line 14: `"""Return basic robot state information."""`
- Line 67: `"""Deleguje do state() i dokleja vision.obstacle (jeśli dostępne)."""`
- Line 68: `base_resp = state()`
- Line 69: `status = getattr(base_resp, "status_code", 200)`
- Line 85: `return jsonify(payload), status`

#### `services/api_core/system_info.py`

- Line 158: `# bateria z LAST_XGO – uzupełnia compat.healthz/state, ale sysinfo może też ją podać:`

#### `services/api_core/vision_api.py`

- Line 32: `def _json_nocache(payload: Any, status: int = 200) -> Response:`
- Line 34: `resp = make_response(jsonify(payload), status)`

#### `services/api_core/voice_local_proxy.py`

- Line 91: `if not obj or obj.get("status") != "ok" or "audio_b64" not in obj:`
- Line 100: `r2 = Response(wav, status=200, mimetype="audio/wav")`
- Line 107: `r3 = Response(body, status=200, mimetype="audio/wav")`
- Line 163: `status = resp.status`
- Line 165: `if status != 200:`
- Line 168: `return _cors(jsonify({"ok": False, "error": f"voice asr http error: {status}", "body": snippet})), 5...`

#### `services/api_core/voice_proxy.py`

- Line 32: `code = resp.status`

#### `services/api_server.py`

- Line 65: `status = 503 if (not res.get("ok") and res.get("status") == 503) else 200`
- Line 66: `return jsonify(res), status`
- Line 87: `@app.route("/face/state", methods=["GET"])`
- Line 99: `from services.api_core.face_api import draw_face  # zwraca (body, status)`
- Line 101: `body, status = draw_face(payload)`
- Line 102: `return _corsify(jsonify(body)), status`
- Line 116: `# health/state/sysinfo/metrics/events/livez/readyz`
- Line 123: `_add_rule("/state", view_func=state_api.state_route)`
- Line 155: `_add_rule("/svc/<name>/status", view_func=services_api.svc_status, methods=["GET"])`
- Line 261: `@app.route("/api/home/status", methods=["GET", "OPTIONS"])`


### sim/

#### `sim/robot.py`

- Line 105: `"""Get current robot state."""`

#### `sim/world.py`

- Line 264: `state = robot.get_state()`
- Line 271: `f"Position: ({state['x']:.2f}, {state['y']:.2f})",`
- Line 272: `f"Angle: {math.degrees(state['angle']):.1f}°",`
- Line 273: `f"Linear: {state['linear_vel']:.3f} m/s",`
- Line 274: `f"Angular: {state['angular_vel']:.3f} rad/s",`


### tests/

#### `tests/acceptance_criteria.py`

- Line 117: `state = robot.get_state()`
- Line 119: `assert "x" in state, "State should contain x position"`
- Line 120: `assert "y" in state, "State should contain y position"`
- Line 121: `assert "angle" in state, "State should contain angle"`
- Line 122: `assert state["x"] == 7.5, "X position should match"`
- Line 123: `assert state["y"] == 3.2, "Y position should match"`

#### `tests/api_compare.sh`

- Line 38: `"/status /api/status"`

#### `tests/api_diag.sh`

- Line 32: `$(basename "$0") smoke         # szybkie sprawdzenie /healthz, /readyz, /api/status...`
- Line 34: `$(basename "$0") latency [N]   # pomiar czasu dla /api/status (domyślnie N=20)`
- Line 94: `echo "# status";            $CURL "$BASE/api/status"         | jq_filter '.system.cpu, .devices.summ...`
- Line 113: `echo "# measuring $n requests to $BASE/api/status"`
- Line 115: `curl -o /dev/null -sS -w "$TIMEFMT" "$BASE/api/status"`

#### `tests/diag_snapshot.sh`

- Line 38: `sec "systemd: status (skróty)"`
- Line 41: `systemctl --no-pager -l status "$s" | sed -n '1,25p' | tee -a "$OUT" || true`
- Line 67: `"http://127.0.0.1:8080/state" \`
- Line 69: `"http://127.0.0.1:8080/api/status" \`

#### `tests/final_verification_sim3.py`

- Line 173: `status = "PASS" if success else "FAIL"`
- Line 174: `print(f"[{status}] {desc}")`
- Line 186: `print("Acceptance Criteria Status:")`

#### `tests/test_api_server_google_home.py`

- Line 41: `status = expected_status`
- Line 44: `status = 200`
- Line 47: `assert status == 401`

#### `tests/test_camera_api.py`

- Line 35: `r = c.get("/state")`
- Line 40: `pytest.xfail("`/state` does not expose a 'camera' block on this build.")`

#### `tests/test_face_anim_api.py`

- Line 26: `fa.STATE.update(`
- Line 80: `assert data["state"]["playing"] is True`
- Line 84: `# sprawdź state`
- Line 85: `rv = c.get("/face/state")`
- Line 87: `st = rv.get_json()["state"]`
- Line 98: `ok = _poll_until(lambda: _client().get("/face/state").get_json()["state"]["playing"] is False, timeo...`

#### `tests/test_face_anim_nullsink.py`

- Line 22: `fa.STATE.update(`
- Line 72: `assert fa.STATE["playing"] is True`
- Line 79: `assert fa.STATE["playing"] is False`

#### `tests/test_face_lcd_anim.py`

- Line 25: `state = requests.get(f"{API}/face/state").json()`
- Line 26: `assert not state["state"]["playing"]`
- Line 37: `assert data["status"] == 503`

#### `tests/test_google_command.py`

- Line 69: `mock_send.return_value = {"ok": True, "result": {"status": "SUCCESS"}}`
- Line 100: `assert cache_data["response"] == {"status": "SUCCESS"}`
- Line 199: `mock_response.text = '{"status": "SUCCESS"}'`
- Line 200: `mock_response.json.return_value = {"status": "SUCCESS"}`
- Line 208: `assert result["result"]["status"] == "SUCCESS"`

#### `tests/test_google_feed.py`

*12 references found. Showing first 5:*

- Line 24: `test_data = {"state": "ok", "timestamp": 123456}`
- Line 59: `"""Test /api/google/status endpoint returns valid JSON."""`
- Line 66: `# Test with non-existent status file`
- Line 69: `response = client.get("/api/google/status")`
- Line 72: `assert "state" in data`

#### `tests/test_simulation_toggle.py`

- Line 15: `"""Save original environment state."""`
- Line 19: `"""Restore original environment state."""`

#### `tests/test_simulator.py`

- Line 22: `"""Test that robot initializes with correct state."""`
- Line 68: `"""Test that robot returns correct state dictionary."""`
- Line 70: `state = robot.get_state()`
- Line 72: `assert isinstance(state, dict)`
- Line 73: `assert "x" in state`
- Line 74: `assert "y" in state`
- Line 75: `assert "angle" in state`
- Line 76: `assert "linear_vel" in state`
- Line 77: `assert "angular_vel" in state`

#### `tests/test_simulator_robot.py`

- Line 19: `"""Test that robot initializes with correct state."""`
- Line 106: `state = robot.get_state()`
- Line 108: `assert state["x"] == 1.5`
- Line 109: `assert state["y"] == 2.5`
- Line 110: `assert state["angle"] == 0.5`
- Line 111: `assert state["linear_vel"] == 0.2`
- Line 112: `assert state["angular_vel"] == 0.3`
- Line 114: `print("✓ Robot state test passed")`

#### `tests/test_state_ptt.py`

*26 references found. Showing first 5:*

- Line 2: `"""Test PTT state machine functionality."""`
- Line 6: `from apps.voice.stream.state import PTTEvent, PTTStateMachine`
- Line 10: `"""Test basic PTT state machine transitions."""`
- Line 13: `# Initial state should be IDLE`
- Line 14: `from apps.voice.stream.state import PTTState`

#### `tests/test_systemd_services.py`

- Line 48: `# We expect at least 15 service files based on current repo state`

#### `tests/test_systemd_smoke.py`

- Line 96: `"""Test that service status can be checked."""`
- Line 100: `["systemctl", scope, "status", service_name],`
- Line 103: `# Status check should not fail completely (service may be inactive, that's OK)`
- Line 126: `# Get initial state`
- Line 139: `# Check if service reached active state`
- Line 140: `state = self._get_service_state(service_name)`
- Line 141: `assert state in ("active", "inactive", "activating"), f"Unexpected state after start: {state}"`
- Line 153: `# Restore initial state`
- Line 161: `"""Get the current state of a service."""`

#### `tests/test_vad_state_reset.py`

- Line 1: `"""Test VAD state reset functionality to prevent loop recording issues."""`
- Line 9: `"""Test that SilenceTail.reset() clears the window state."""`
- Line 30: `"""Test that WebRtcActivity.reset() properly resets internal state."""`
- Line 41: `# Reset should clear internal state`
- Line 44: `# After reset, the VAD should be in a clean state`
- Line 50: `"""Test that demonstrates the problem: VAD state persists between cycles."""`
- Line 52: `# by directly manipulating the SilenceTail state`
- Line 78: `# Reset VAD state before next recording cycle`
- Line 110: `# Restore original state`

#### `tests/test_vision_dispatcher.py`

- Line 28: `disp.STATE.present = False`
- Line 29: `disp.STATE.consecutive_pos = 0`
- Line 30: `disp.STATE.confidence = 0.0`
- Line 36: `assert disp.STATE.present is False`
- Line 38: `# 2) drugi pozytyw — powinniśmy wejść w present=True i mieć vision.state`
- Line 40: `assert disp.STATE.present is True`
- Line 41: `assert any(t == "vision.state" and p.get("present") is True for t, p in published)`
- Line 47: `assert any(t == "vision.state" and p.get("present") is False for t, p in published)`

#### `tests/test_voice_ptt_state.py`

*66 references found. Showing first 5:*

- Line 1: `"""Test suite for PTT state machine."""`
- Line 7: `from apps.voice.stream.state import PTTEvent, PTTState, PTTStateMachine`
- Line 11: `"""Test PTT state machine behavior."""`
- Line 14: `"""Test initial state is IDLE."""`
- Line 15: `fsm = PTTStateMachine()`

#### `tests/test_voice_service_ui_state.py`

- Line 21: `Regression tests for VoiceService UI state publishing.`
- Line 108: `return [payload["state"] for topic, payload in publisher.messages if topic == "ui.state"]`

#### `tests/test_voice_stream_smoke.py`

- Line 141: `"""Test PTT configuration and state."""`

#### `tests/test_voice_streaming.py`

- Line 17: `to verify proper message handling, state transitions, and audio flow.`
- Line 129: `# Verify state change`
- Line 130: `states = [msg for msg in mock_ui_publisher.messages if msg[0] == "ui.state"]`
- Line 132: `assert states[0][1]["state"] == "hearing"`
- Line 171: `"""Test UI state change publishing."""`
- Line 174: `# Test state change`
- Line 180: `assert topic == "ui.state"`
- Line 181: `assert payload["state"] == "hearing"`
- Line 184: `# Test no duplicate publishing for same state`

#### `tests/test_voice_ws_close.py`

- Line 53: `# Should clean up state`
- Line 80: `# Should still clean up state`

#### `tests/verify_sim1_acceptance.py`

- Line 109: `passed = sum(1 for _, status, _ in criteria if status)`


---

## External References

References to code outside the project directory (e.g., `/robot/`):

**Total external references found**: 51

### `apps/camera/preview_lcd.py`

- Line 32: `SNAP_DIR / SNAP_BASE             # katalog na snapshots (RAW/PROC); domyślnie ~/robot/snapshots`

### `apps/camera/preview_lcd_hybrid.py`

- Line 21: `SNAP = Snapper(base_dir=os.getenv("SNAP_BASE", "/home/pi/robot/snapshots"))`

### `apps/camera/preview_lcd_ssd.py`

- Line 6: `# Preview + MobileNet-SSD (Caffe) — zapis RAW/PROC do /home/pi/robot/snapshots (atomowo)`
- Line 23: `SNAP_DIR = os.getenv("SNAP_DIR") or os.getenv("SNAP_BASE") or "/home/pi/robot/snapshots"`

### `apps/camera/preview_lcd_takeover.py`

- Line 19: `SNAP = Snapper(base_dir=os.getenv("SNAP_BASE", "/home/pi/robot/snapshots"))`
- Line 25: `LAST_FRAME_PATH = os.environ.get("LAST_FRAME_PATH", "/home/pi/robot/data/last_frame.jpg")`

### `apps/camera/ssd_preview_writer.py`

- Line 4: `# SSD preview + pewny zapis RAW/PROC do /home/pi/robot/snapshots (atomowo) + LCD`
- Line 12: `SNAP_DIR = os.getenv("SNAP_BASE", "/home/pi/robot/snapshots")`

### `apps/google_bridge/puller.py`

- Line 11: `DATA_DIR: Base data directory (default: ~/robot/data)`

### `apps/main.py`

- Line 11: `- /home/pi/robot/data/flags/motion.enable   → pozwolenie na ruch`
- Line 12: `- /home/pi/robot/data/flags/estop.on        → twardy E-Stop`

### `apps/ui/manager.py`

- Line 27: `AUDIO_HOOK = os.getenv("UI_AUDIO_HOOK", "/home/pi/robot/apps/ui/volume_hooks.sh")`

### `apps/ui/volume_hooks.sh`

- Line 4: `dim) /home/pi/robot/scripts/util_volume.py set ${UI_AUDIO_DIM_PCT:-20} ;;`
- Line 5: `off) [ "${UI_AUDIO_OFF_MUTE:-1}" = "1" ] && /home/pi/robot/scripts/util_volume.py mute on ;;`
- Line 6: `on)  /home/pi/robot/scripts/util_volume.py mute off ; /home/pi/robot/scripts/util_volume.py set ${UI_BRIGHT_LEVEL:-80} ;;`

### `apps/vision/detector_hog.py`

- Line 18: `SNAP_DIR = os.getenv("SNAP_BASE", "/home/pi/robot/snapshots")`

### `apps/vision/edge_preview.py`

- Line 10: `SNAP_DIR = os.environ.get("SNAP_DIR", "/home/pi/robot/snapshots")`
- Line 18: `LAST = os.environ.get("LAST_FRAME", "/home/pi/robot/data/last_frame.jpg")`

### `apps/vision/obstacle_roi.py`

- Line 43: `PROC_PATH = os.getenv("PROC_PATH", "/home/pi/robot/snapshots/proc.jpg")`
- Line 44: `RAW_PATH = os.getenv("RAW_PATH", "/home/pi/robot/snapshots/raw.jpg")  # opcjonalny`
- Line 45: `DATA_DIR = os.getenv("DATA_DIR", "/home/pi/robot/data")`
- Line 72: `OBST_ANN_PATH = os.getenv("OBST_ANN_PATH", "/home/pi/robot/snapshots/obst_annot.jpg")`

### `apps/voice/web.py`

- Line 64: `PIPER_MODEL_DIR = os.getenv("PIPER_MODEL_DIR", "/home/pi/robot/models/piper").rstrip("/")`
- Line 68: `VOSK_MODEL = os.getenv("VOSK_MODEL", "/home/pi/robot/models/vosk/vosk-model-small-pl-0.22")`
- Line 458: `f'{os.getenv("PIPER_MODEL_DIR", "/home/pi/robot/models/piper").rstrip("/")}/'`

### `scripts/dev_face-presenter.py`

- Line 131: `sys.path[:0] = ["/home/pi/robot", "/home/pi/robot/apps"]`

### `scripts/dev_lcd-clear.py`

- Line 14: `sys.path[:0] = ["/home/pi/robot", "/home/pi/robot/apps"]`

### `scripts/dev_lcd-show-raw.py`

- Line 17: `sys.path[:0] = ["/home/pi/robot", "/home/pi/robot/apps"]`

### `scripts/dev_lcd-testcard.py`

- Line 13: `sys.path[:0] = ["/home/pi/robot", "/home/pi/robot/apps"]`

### `scripts/dev_panel-nuke.py`

- Line 14: `sys.path[:0] = ["/home/pi/robot", "/home/pi/robot/apps"]`

### `scripts/dev_panel-reset.py`

- Line 16: `sys.path[:0] = ["/home/pi/robot", "/home/pi/robot/apps"]`

### `scripts/diag_framebuffer-grab.py`

- Line 13: `#   SNAP_OUT      -> plik wyjściowy (domyślnie ~/robot/snapshots/lcd_fb.jpg)`
- Line 87: `out = os.path.expanduser(os.getenv("SNAP_OUT", "~/robot/snapshots/lcd_fb.jpg"))`

### `scripts/diag_lcd-raw.py`

- Line 19: `sys.path[:0] = ["/home/pi/robot", "/home/pi/robot/apps"]`

### `scripts/diag_validate-systemd-paths.py`

- Line 119: `if path_str.startswith('/home/pi/robot/'):`
- Line 121: `rel_path = path_str.replace('/home/pi/robot/', '')`

### `scripts/sys_splash-info.sh`

- Line 20: `#   SPLASH_LOGO=/home/pi/robot/data/splash_logo.png`

### `scripts/sys_voice-run.sh`

- Line 63: `export RECORDINGS_DIR="${RECORDINGS_DIR:-/home/pi/robot/data/recordings}"`
- Line 93: `exec /usr/bin/python3 -u /home/pi/robot/apps/voice/main.py`

### `scripts/systemd-sync.sh`

- Line 3: `# Utrzymuje tylko wskazane unity jako symlinki do ~/robot/systemd/*`

### `scripts/util_volume-hooks.sh`

- Line 4: `dim) /home/pi/robot/scripts/util_volume.py set ${UI_AUDIO_DIM_PCT:-20} ;;`
- Line 5: `off) [ "${UI_AUDIO_OFF_MUTE:-1}" = "1" ] && /home/pi/robot/scripts/util_volume.py mute on ;;`
- Line 6: `on)  /home/pi/robot/scripts/util_volume.py mute off ; /home/pi/robot/scripts/util_volume.py set ${UI_XGO_BRIGHT:-80} ;;`

### `services/api_core/vision_api.py`

- Line 106: `# Jeśli compat ma DATA_DIR — użyj. W przeciwnym razie: ~/robot/data obok snapshots.`

### `tests/test_suite.sh`

- Line 17: `run mkdir -p ~/robot/data/flags`
- Line 18: `run touch ~/robot/data/flags/motion.enable`
- Line 19: `run rm -f  ~/robot/data/flags/estop.on`

### `tests/test_systemd_services.py`

- Line 137: `# Check absolute paths within /home/pi/robot/`
- Line 138: `if path.is_absolute() and path_str.startswith("/home/pi/robot/"):`
- Line 139: `rel_path = path_str.replace("/home/pi/robot/", "")`

### `tests/web_control_diag.sh`

- Line 7: `OUTDIR="${OUTDIR:-$HOME/robot/tests/out}"`

---

## Analysis Methodology

This report was generated by scanning the following subdirectories:

- `apps/`
- `services/`
- `common/`
- `drivers/`
- `scripts/`
- `tests/`
- `sim/`
- `config/`
- `examples/`
- `tools/`
- `web/`
- `systemd/`

The analysis searched for:
- Import statements
- Technology-specific keywords
- Configuration references
- API calls and library usage

**Note**: Root-level files were excluded from this analysis as per requirements.

