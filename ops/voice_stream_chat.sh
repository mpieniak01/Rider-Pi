#!/usr/bin/env bash
# voice_stream_chat.sh — configure environment, free audio devices and run a realtime chat demo.

set -euo pipefail

# --- paths --------------------------------------------------------------------
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
cd "${REPO_ROOT}"

# --- source ~/.bash_profile (klucze i poświadczenia pobieramy STĄD) ----------
if [ -f "$HOME/.bash_profile" ]; then
  # shellcheck disable=SC1090
  . "$HOME/.bash_profile"
fi

# --- env defaults (ustaw tylko, jeśli nie podano w profilu) -------------------
: "${OPENAI_BASE:=https://api.openai.com/v1}"
: "${OPENAI_REALTIME_ENDPOINT:=wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview}"

DEFAULT_CONFIG="${REPO_ROOT}/config/voice_streaming.toml"
DEFAULT_ALSA="${REPO_ROOT}/config/alsa/asoundrc.wm8960"

: "${VOICE_CONFIG:=${DEFAULT_CONFIG}}"
if [ -z "${ALSA_CONFIG_PATH:-}" ] && [ -f "${DEFAULT_ALSA}" ]; then
  ALSA_CONFIG_PATH="${DEFAULT_ALSA}"
fi

# Telemetria/logi i stabilniejsze I/O
: "${PYTHONUNBUFFERED:=1}"
: "${VOICE_WS_LOG:=1}"
: "${VOICE_WS_DUMP:=1}"

# Wymagane: klucz po sourcowaniu profilu
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "[voice.ops] ERROR: OPENAI_API_KEY is not set (missing in ~/.bash_profile?)." >&2
  echo "           Add to ~/.bash_profile, e.g.: export OPENAI_API_KEY='sk-...'" >&2
  exit 2
fi

# Eksport wszystkiego co używamy dalej
export OPENAI_API_KEY OPENAI_BASE OPENAI_REALTIME_ENDPOINT \
       VOICE_CONFIG ALSA_CONFIG_PATH PYTHONUNBUFFERED VOICE_WS_LOG VOICE_WS_DUMP

# PYTHONPATH do lokalnych importów
export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"

# --- info ---------------------------------------------------------------------
echo "[voice.ops] Using VOICE_CONFIG=${VOICE_CONFIG}"
[ -n "${ALSA_CONFIG_PATH:-}" ] && echo "[voice.ops] ALSA_CONFIG_PATH=${ALSA_CONFIG_PATH}" || \
  echo "[voice.ops] ALSA_CONFIG_PATH is not set (Pulse/HDMI may be used by system)."
echo "[voice.ops] OPENAI_REALTIME_ENDPOINT=${OPENAI_REALTIME_ENDPOINT}"
echo "[voice.ops] PYTHONUNBUFFERED=${PYTHONUNBUFFERED} VOICE_WS_LOG=${VOICE_WS_LOG} VOICE_WS_DUMP=${VOICE_WS_DUMP}"

# --- free ALSA devices --------------------------------------------------------
echo "[voice.ops] Freeing ALSA devices..."
KILL_CMD="fuser"
if command -v sudo >/dev/null 2>&1; then
  KILL_CMD="sudo fuser"
fi
for dev in /dev/snd/pcmC0D0p /dev/snd/pcmC0D0c; do
  if [ -e "${dev}" ]; then
    ${KILL_CMD} -k "${dev}" 2>/dev/null || true
  fi
done

# --- run realtime chat demo ---------------------------------------------------
echo "[voice.ops] Starting realtime chat demo..."
python3 - <<'PY'
import asyncio
import os
from pathlib import Path

# (opcjonalnie) gdyby skrypt nie był użyty, Pythonowy fallback mógłby
# sam doczytać profil — tutaj zakładamy, że bash już ustawił ENV.

from apps.voice import config as voice_config
from apps.voice.stream.service import StreamingVoiceService
from apps.voice.stream.state import PTTEvent

CONFIG_PATH = Path(os.environ.get("VOICE_CONFIG", "config/voice_streaming.toml"))
if not CONFIG_PATH.exists():
    raise SystemExit(f"Voice config not found: {CONFIG_PATH}")

cfg = voice_config.load(CONFIG_PATH)

# stream.auth z ENV (nie wypisujemy klucza do logów)
stream_cfg = cfg.setdefault("stream", {})
stream_cfg.setdefault("auth", "env:OPENAI_API_KEY")

endpoint = os.environ.get("OPENAI_REALTIME_ENDPOINT")
if endpoint:
    stream_cfg["endpoint"] = endpoint

prompt = os.environ.get(
    "VOICE_STREAM_PROMPT",
    'Powiedz: "Test transmisji audio" i zakończ odpowiedź jednym zdaniem.',
)

async def main() -> None:
    service = StreamingVoiceService(cfg)
    loop = asyncio.get_running_loop()
    service._loop = loop  # utrzymujemy spójność z istniejącym kodem
    import websockets
    service._ws_module = websockets

    # 1) Transport WS
    if not await service._initialize_transport():
        raise SystemExit("Failed to initialize realtime transport")

    try:
        # 2) Inicjalizacja sesji + instrukcje
        await service._send_session_init()
        if service._session_prefs is not None:
            service._session_prefs.instructions = prompt

        # 3) Start PTT + handler wiadomości + TTS
        service.ptt_state.start_interaction()
        service.ptt_state.transition(PTTEvent.START)
        service._message_handler_task = asyncio.create_task(service._message_handler_loop())
        service._start_tts_player()

        # 4) Poproś o odpowiedź (bez input_audio – to demko TTS)
        await service._send_response_create()

        # 5) Czekaj na koniec odpowiedzi (z limitem)
        try:
            await asyncio.wait_for(service._wait_for_completion(), timeout=45)
        except asyncio.TimeoutError:
            raise SystemExit("Realtime response timeout")
    finally:
        # 6) Sprzątanie: player, taski, WS
        await service._cleanup()

asyncio.run(main())
PY

STATUS=$?
if [ ${STATUS} -eq 0 ]; then
  echo "[voice.ops] Realtime chat demo finished successfully."
else
  echo "[voice.ops] Realtime chat demo failed with status ${STATUS}." >&2
fi

exit ${STATUS}
