#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONUNBUFFERED=1

echo "[voice-once] ROOT=$ROOT"
echo "[voice-once] $(date --iso-8601=seconds)"
echo "[voice-once] Apply WM8960 mixer levels…"
"$ROOT/config/wm8960-apply.sh"

# Log do podglądu w drugim oknie: tail -f /tmp/voice-once.log
exec python -m apps.voice.main \
  --config "$ROOT/config/voice.toml" \
  once --mode file --hotword ptt \
  --capture sample_rate=16000 channels=1 \
  --tts format=wav \
  beep=true \
| tee /tmp/voice-once.log
