#!/usr/bin/env bash
# voice-run.sh — uruchamia /home/pi/robot/apps/voice/main.py z sensownymi domyślnymi ENV
# Użycie:
#   ./voice-run.sh             # domyślnie tryb BUS (VOICE_STANDALONE=0)
#   ./voice-run.sh bus         # wymuś tryb BUS
#   ./voice-run.sh standalone  # wymuś tryb STANDALONE (mowa + chat w voice)
#   HOTWORD_THRESHOLD=0.62 ./voice-run.sh standalone   # dowolne ENV możesz nadpisywać

set -euo pipefail

# ── Klucz OpenAI z ~/.bash_profile (bezpiecznie) ──────────────────────────────
if [[ -f "$HOME/.bash_profile" ]]; then
  # Załaduj zmienne (w tym OPENAI_API_KEY) jeśli brak w środowisku
  if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    OPENAI_API_KEY="$(
      bash -lc 'source ~/.bash_profile >/dev/null 2>&1; printf "%s" "$OPENAI_API_KEY"'
    )"
    export OPENAI_API_KEY
  fi
fi

# ── Locale/IO (żeby logi nie krzaczyły polskich znaków) ───────────────────────
export PYTHONIOENCODING=UTF-8
export LC_ALL=C.UTF-8
export LANG=C.UTF-8

# ── Ścieżka projektu dla importów (common.bus itd.) ───────────────────────────
export PYTHONPATH="/home/pi/robot:${PYTHONPATH:-}"

# ── Domyślne ENV (możesz je nadpisać przed ./voice-run.sh) ───────────────────
export ALSA_DEVICE="${ALSA_DEVICE:-plughw:1,0}"

# Hotword / cechy
export HOTWORD_THRESHOLD="${HOTWORD_THRESHOLD:-0.60}"
export EXTRACTOR_GAIN="${EXTRACTOR_GAIN:-1.0}"

# VAD/końcówka ciszy
export VAD_MODE="${VAD_MODE:-3}"
export VAD_FRAME_MS="${VAD_FRAME_MS:-20}"
export VAD_SILENCE_TAIL_MS="${VAD_SILENCE_TAIL_MS:-300}"
export VAD_MAX_LEN_S="${VAD_MAX_LEN_S:-4.0}"
export ENERGY_CUTOFF_DBFS="${ENERGY_CUTOFF_DBFS:- -36.0}"
export ENERGY_TAIL_MS="${ENERGY_TAIL_MS:-180}"

# Aplay bufory (stabilniejsze odtwarzanie)
export ALSA_BUFFER_US="${ALSA_BUFFER_US:-50000}"
export ALSA_PERIOD_US="${ALSA_PERIOD_US:-12000}"

# TTS strumieniowe (jeśli w trybie standalone)
export STREAM_TTS="${STREAM_TTS:-1}"
export STREAM_CHUNK="${STREAM_CHUNK:-8192}"
export STREAM_PITCH="${STREAM_PITCH:-0.0}"
export STREAM_TEE_OUTPUT="${STREAM_TEE_OUTPUT:-0}"

# Nagrania (opcjonalne kopie wej/wyj)
export RECORDINGS_DIR="${RECORDINGS_DIR:-/home/pi/robot/data/recordings}"
export KEEP_INPUT_WAV="${KEEP_INPUT_WAV:-0}"
export KEEP_OUTPUT_WAV="${KEEP_OUTPUT_WAV:-0}"

# Krótki „ding” po hotword (ms)
export DING_PLAY_MS="${DING_PLAY_MS:-200}"

# ── Wybór trybu: BUS vs STANDALONE ────────────────────────────────────────────
MODE="${1:-bus}"
case "$MODE" in
  bus|BUS)          export VOICE_STANDALONE="${VOICE_STANDALONE:-0}" ;;
  standalone|solo)  export VOICE_STANDALONE=1 ;;
  *)                # nic nie podano → zostaw co w środowisku, albo domyślnie BUS
                    export VOICE_STANDALONE="${VOICE_STANDALONE:-0}" ;;
esac

# ── Katalog nagrań ────────────────────────────────────────────────────────────
mkdir -p "$RECORDINGS_DIR"

echo "== voice-run =="
echo "  MODE:            ${MODE}  (VOICE_STANDALONE=${VOICE_STANDALONE})"
echo "  ALSA_DEVICE:     ${ALSA_DEVICE}"
echo "  HOTWORD_THRESHOLD=${HOTWORD_THRESHOLD}  EXTRACTOR_GAIN=${EXTRACTOR_GAIN}"
echo "  VAD: mode=${VAD_MODE} frame=${VAD_FRAME_MS}ms tail=${VAD_SILENCE_TAIL_MS}ms max=${VAD_MAX_LEN_S}s"
echo "  ENERGY: cutoff=${ENERGY_CUTOFF_DBFS}dBFS tail=${ENERGY_TAIL_MS}ms"
echo "  RECORDINGS_DIR:  ${RECORDINGS_DIR}"
echo

# ── Uruchomienie (line-buffered logi) ─────────────────────────────────────────
export PYTHONUNBUFFERED=1
exec /usr/bin/python3 -u /home/pi/robot/apps/voice/main.py
