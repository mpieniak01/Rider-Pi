#!/usr/bin/env bash
# voice_stream_chat.sh — configure environment, free audio devices and run a realtime chat demo.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
cd "${REPO_ROOT}"

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "[voice.ops] ERROR: OPENAI_API_KEY is not set." >&2
  exit 1
fi

DEFAULT_CONFIG="${REPO_ROOT}/config/voice_streaming.toml"
DEFAULT_ALSA="${REPO_ROOT}/config/alsa/asoundrc.wm8960"

if [ -z "${VOICE_CONFIG:-}" ]; then
  export VOICE_CONFIG="${DEFAULT_CONFIG}"
fi

if [ -f "${DEFAULT_ALSA}" ] && [ -z "${ALSA_CONFIG_PATH:-}" ]; then
  export ALSA_CONFIG_PATH="${DEFAULT_ALSA}"
fi

export OPENAI_REALTIME_ENDPOINT="${OPENAI_REALTIME_ENDPOINT:-wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview}" 
export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"

echo "[voice.ops] Using VOICE_CONFIG=${VOICE_CONFIG}"
[ -n "${ALSA_CONFIG_PATH:-}" ] && echo "[voice.ops] ALSA_CONFIG_PATH=${ALSA_CONFIG_PATH}"
echo "[voice.ops] OPENAI_REALTIME_ENDPOINT=${OPENAI_REALTIME_ENDPOINT}"

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

echo "[voice.ops] Starting realtime chat demo..."
python3 - <<'PY'
import asyncio
import os
from pathlib import Path

from apps.voice import config as voice_config
from apps.voice.stream.service import StreamingVoiceService
from apps.voice.stream.state import PTTEvent

CONFIG_PATH = Path(os.environ.get("VOICE_CONFIG", "config/voice_streaming.toml"))
if not CONFIG_PATH.exists():
    raise SystemExit(f"Voice config not found: {CONFIG_PATH}")

cfg = voice_config.load(CONFIG_PATH)
stream_cfg = cfg.setdefault("stream", {})
stream_cfg.setdefault("auth", "env:OPENAI_API_KEY")
endpoint = os.environ.get("OPENAI_REALTIME_ENDPOINT")
if endpoint:
    stream_cfg["endpoint"] = endpoint

prompt = os.environ.get(
    "VOICE_STREAM_PROMPT",
    "Powiedz: \"Test transmisji audio\" i zakończ odpowiedź jednym zdaniem.",
)

async def main() -> None:
    service = StreamingVoiceService(cfg)
    loop = asyncio.get_running_loop()
    service._loop = loop

    if not await service._initialize_transport():
        raise SystemExit("Failed to initialize realtime transport")

    try:
        await service._send_session_init()
        if service._session_prefs is not None:
            service._session_prefs.instructions = prompt
        service.ptt_state.start_interaction()
        service.ptt_state.transition(PTTEvent.START)
        service._message_handler_task = asyncio.create_task(service._message_handler_loop())
        service._start_tts_player()
        await service._send_response_create()
        try:
            await asyncio.wait_for(service._wait_for_completion(), timeout=45)
        except asyncio.TimeoutError:
            raise SystemExit("Realtime response timeout")
    finally:
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
