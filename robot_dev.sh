#!/usr/bin/env bash
# robot_dev.sh — dev launcher (broker | voice | chat | face | nlu | tts2face | all | restart | stop | status | takeover | help)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

ts(){ date +"%H:%M:%S"; }
say(){ echo "[$(ts)] $*"; }

# --- ENV domyślne (można nadpisać przed wywołaniem) ---
: "${BUS_HOST:=127.0.0.1}"
: "${BUS_PUB:=5555}"
: "${BUS_SUB:=5556}"
: "${FACE_BACKEND:=lcd}"
: "${FACE_LCD_ROTATE:=270}"
: "${VOICE_STANDALONE:=0}"   # przy all: 0 => uruchom też chat

# --- pomocnicze: odpalanie w tle do 'all' ---
run_bg () {
  # $1=nazwa, $2...=komenda
  local name="$1"; shift
  nohup bash -lc "$*" >/dev/null 2>&1 &
  say "start (bg): $name pid=$!"
}

usage () {
  cat <<'EOF'
Użycie:
  robot_dev.sh broker        # uruchom broker (FG)
  robot_dev.sh voice         # uruchom voice  (FG)
  robot_dev.sh chat          # uruchom chat   (FG)
  robot_dev.sh face          # UI (LCD/TK; honoruje FACE_* ENV)
  robot_dev.sh nlu           # NLU (audio.transcript -> motion.cmd)
  robot_dev.sh tts2face      # mostek tts.speak -> ui.face.set
  robot_dev.sh takeover      # przejęcie ekranu: pkill root-start app + zwolnij SPI
  robot_dev.sh all           # broker + voice + (chat gdy VOICE_STANDALONE=0) + face
  robot_dev.sh restart       # stop → all
  robot_dev.sh stop          # awaryjny STOP + ubij procesy + domknij okna
  robot_dev.sh status        # porty i procesy
  robot_dev.sh help          # to okno

Przydatne ENV dla face:
  FACE_BACKEND=lcd|tk        # domyślnie lcd (gdy DISPLAY brak → tk pomijany)
  FACE_LCD_ROTATE=0|90|180|270  # typowo 270 na Rider-Pi
  FACE_GUIDE=0|1
  FACE_BENCH=0|1
BUS:
  BUS_HOST=127.0.0.1 BUS_PUB=5555 BUS_SUB=5556
EOF
}

takeover () {
  if [[ -x "$ROOT/scripts/takeover.sh" ]]; then
    say "takeover: scripts/takeover.sh"
    "$ROOT/scripts/takeover.sh" || true
  else
    say "takeover: brak scripts/takeover.sh — pomijam"
  fi
}

start_broker () {
  say "start: broker"
  exec env BUS_HOST="$BUS_HOST" BUS_PUB="$BUS_PUB" BUS_SUB="$BUS_SUB" \
    python3 scripts/broker.py
}

start_voice () {
  say "start: voice"
  exec env BUS_HOST="$BUS_HOST" BUS_PUB="$BUS_PUB" BUS_SUB="$BUS_SUB" \
    python3 -m apps.voice.main
}

start_chat () {
  say "start: chat"
  exec env BUS_HOST="$BUS_HOST" BUS_PUB="$BUS_PUB" BUS_SUB="$BUS_SUB" \
    python3 -m apps.chat.main
}

start_face () {
  takeover
  say "start: face (FACE_BACKEND=$FACE_BACKEND ROTATE=$FACE_LCD_ROTATE)"
  exec env BUS_HOST="$BUS_HOST" BUS_PUB="$BUS_PUB" BUS_SUB="$BUS_SUB" \
    FACE_BACKEND="$FACE_BACKEND" FACE_LCD_ROTATE="$FACE_LCD_ROTATE" \
    python3 -m apps.ui.face
}

# --- NOWE: NLU i TTS→Face ---
start_nlu () {
  say "start: nlu"
  exec env BUS_HOST="$BUS_HOST" BUS_PUB="$BUS_PUB" BUS_SUB="$BUS_SUB" \
    python3 -m apps.nlu.main
}

start_tts2face () {
  say "start: tts2face (bridge tts.speak -> ui.face.set)"
  exec env BUS_HOST="$BUS_HOST" BUS_PUB="$BUS_PUB" BUS_SUB="$BUS_SUB" \
    python3 -m apps.ui.tts2face
}

# --- status/stop ---
status () {
  say "procesy (pgrep -f):"
  for pat in \
    "scripts/broker.py" \
    "apps.voice" \
    "apps.chat" \
    "apps.ui.face" \
    "apps.nlu.main" \
    "apps.ui.tts2face"
  do
    if pgrep -f "$pat" >/dev/null 2>&1; then
      pgrep -fa "$pat" | sed 's/^/  ✓ /'
    else
      echo "  ✗ $pat"
    fi
  done
}

stop_all () {
  say "STOP: SIGINT -> SIGKILL"
  for pat in \
    "apps.ui.tts2face" \
    "apps.nlu.main" \
    "apps.ui.face" \
    "apps.chat" \
    "apps.voice" \
    "scripts/broker.py"
  do
    pids="$(pgrep -f "$pat" || true)"
    if [[ -n "${pids:-}" ]]; then
      for p in $pids; do
        say "kill -INT $p ($pat)"; kill -INT "$p" || true
      done
    fi
  done
  sleep 1
  for pat in \
    "apps.ui.tts2face" \
    "apps.nlu.main" \
    "apps.ui.face" \
    "apps.chat" \
    "apps.voice" \
    "scripts/broker.py"
  do
    pids="$(pgrep -f "$pat" || true)"
    if [[ -n "${pids:-}" ]]; then
      for p in $pids; do
        say "kill -9 $p ($pat)"; kill -9 "$p" || true
      done
    fi
  done
}

start_all () {
  say "all: start (bg)"
  run_bg broker   "env BUS_HOST='$BUS_HOST' BUS_PUB='$BUS_PUB' BUS_SUB='$BUS_SUB' python3 scripts/broker.py"
  sleep 0.2
  run_bg voice    "env BUS_HOST='$BUS_HOST' BUS_PUB='$BUS_PUB' BUS_SUB='$BUS_SUB' python3 -m apps.voice.main"
  if [[ "${VOICE_STANDALONE}" == "0" ]]; then
    run_bg chat   "env BUS_HOST='$BUS_HOST' BUS_PUB='$BUS_PUB' BUS_SUB='$BUS_SUB' python3 -m apps.chat.main"
  fi
  run_bg face     "env BUS_HOST='$BUS_HOST' BUS_PUB='$BUS_PUB' BUS_SUB='$BUS_SUB' FACE_BACKEND='$FACE_BACKEND' FACE_LCD_ROTATE='$FACE_LCD_ROTATE' python3 -m apps.ui.face"
  say "all: done (sprawdź ./robot_dev.sh status)"
}

# --- dispatch ---
case "${1:-help}" in
  broker)     start_broker ;;
  voice)      start_voice ;;
  chat)       start_chat ;;
  face)       start_face ;;
  nlu)        start_nlu ;;           # <-- NOWE
  tts2face)   start_tts2face ;;      # <-- NOWE
  takeover)   takeover ; exit 0 ;;
  all)        start_all ; exit 0 ;;
  restart)    stop_all ; start_all ; exit 0 ;;
  stop)       stop_all ; exit 0 ;;
  status)     status ; exit 0 ;;
  help|-h|--help|"") usage ; exit 0 ;;
  *)          say "nieznane polecenie: $1"; usage ; exit 1 ;;
esac
