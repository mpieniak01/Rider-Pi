#!/usr/bin/env bash
# voice-once.sh — Modern example: single voice interaction with WM8960
# 
# This script demonstrates the recommended pattern:
# - Uses tools/load_config.sh for environment setup
# - Passes config file explicitly to Python
# - Applies hardware setup (WM8960 mixer) before starting
#
# Użycie:
#   ./voice-once.sh
#   
# See docs/CONFIG_POLICY.md for full configuration policy.

set -euo pipefail

# Load configuration helpers
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../tools/load_config.sh"

# Setup environment (RIDER_ROOT, config paths, API key, etc.)
setup_voice_env

# Apply WM8960 mixer settings
echo "[voice-once] Applying WM8960 mixer levels…" >&2
"$RIDER_CONFIG_DIR/alsa/wm8960-apply.sh" || {
  echo "[voice-once] WARNING: Failed to apply WM8960 settings (may not be available)" >&2
}

# Run voice in once mode with config
echo "[voice-once] Starting at $(date --iso-8601=seconds)" >&2
exec python -m apps.voice.main \
  --config "$RIDER_CONFIG_DIR/voice.toml" \
  once --mode file --hotword ptt \
  --capture sample_rate=16000 channels=1 \
  --tts format=wav \
  beep=true \
| tee /tmp/voice-once.log
