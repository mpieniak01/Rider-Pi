#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  robot_dev.sh — DEV helper do ręcznego startu/stopu komponentów Rider-Pi
#
#  • Bez systemd: prosty start/stop/status, logi na żywo.
#  • Czyta .env (BUS_PUB_PORT/BUS_SUB_PORT, VOICE_STANDALONE, FACE_* itp.).
#  • Komendy:
#      broker        – uruchom broker (FG)
#      voice         – uruchom voice  (FG)
#      chat          – uruchom chat   (FG)
#      face          – UI (apps/ui/face.py; LCD/TK wg ENV) [FG]
#      takeover      – tylko przejęcie ekranu: zabij domyślną appkę i trzymających SPI
#      all           – broker + voice + (chat gdy VOICE_STANDALONE=0) + face
#      restart       – stop → all
#      stop          – awaryjny STOP + ubij procesy + domknij okna
#      status        – porty i działające procesy
#      help          – pomoc
#
#  Przykłady:
#    FACE_BACKEND=lcd FACE_GUIDE=1 FACE_HEAD_KY=1.12 ./robot_dev.sh face
#    ./robot_dev.sh takeover && ./robot_dev.sh face
# ──────────────────────────────────────────────────────────────────────────────

set -Eeuo pipefail
IFS=$'\n\t'
LANG=C.UTF-8

ROOT="/home/pi/robot"
VOICE="${ROOT}/apps/voice/main.py"
CHAT="${ROOT}/apps/chat/main.py"
BROKER="${ROOT}/scripts/broker.py"
PUB="${ROOT}/scripts/pub.py"
FACE="${ROOT}/apps/ui/face.py"      # NOWY UI (dawne face2.py)

log() { printf "[%(%H:%M:%S)T] %s\n" -1 "$*"; }

# profil użytkownika (klucze itp.)
if [[ -f "$HOME/.bash_profile" ]]; then
  set +u; . "$HOME/.bash_profile" >/dev/null 2>&1 || true; set -u
fi

export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"

# ENV (.env)
if [[ -f "${ROOT}/.env" ]]; then
  set +u; set -a; . "${ROOT}/.env"; set +a; set -u
fi
BUS_PUB_PORT="${BUS_PUB_PORT:-5555}"
BUS_SUB_PORT="${BUS_SUB_PORT:-5556}"

in_path() { command -v "$1" >/dev/null 2>&1; }

pids_of() { pgrep -fa python3 | grep -F "$1" || true; }
kill_of() {
  local what="${1:-}"; [[ -z "$what" ]] && return 0
  pgrep -f "$what" >/dev/null 2>&1 || return 0
  pkill -TERM -f "$what" || true
}
check_port() {
  local port="$1"
  (ss -ltpn 2>/dev/null | grep -q ":${port} ") && echo "LISTEN:${port}" || echo "free:${port}"
}

# ── przejęcie ekranu / magistrali SPI (rootowa appka startowa) ────────────────
STARTUP_KILL_RE=${STARTUP_KILL_RE:-"remix\.py|mian\.py|main\.py|demo.*\.py|app_.*\.py"}
kill_startup() {
  log "takeover: pkill -f '${STARTUP_KILL_RE}' (sudo)"
  sudo pkill -TERM -f "${STARTUP_KILL_RE}" 2>/dev/null || true
  sleep 0.2
}
kill_spi_holders() {
  if in_path fuser; then
    local pids
    pids=$(sudo fuser -v /dev/spidev0.0 /dev/spidev0.1 2>/dev/null | awk 'NF>=2 && $2 ~ /^[0-9]+$/ {print $2}' | sort -u || true)
    if [[ -n "$pids" ]]; then
      log "takeover: SPI held by: $pids → SIGTERM/SIGKILL"
      sudo kill -TERM $pids 2>/dev/null || true
      sleep 0.4
      for p in $pids; do sudo kill -0 "$p" 2>/dev/null && sudo kill -KILL "$p" 2>/dev/null || true; done
    else
      log "takeover: SPI not held"
    fi
  else
    log "takeover: fuser not found — skipping"
  fi
}
cmd_takeover_only() { kill_startup; kill_spi_holders; }

# Nowe okno; po zakończeniu zostaw komunikat i czekaj na ENTER (nie zamykaj od razu).
term() {
  local title="$1"; shift
  local cmd="$*"
  if [[ -n "${DISPLAY:-}" ]] && in_path lxterminal; then
    lxterminal -t "$title" -e bash -lc "$cmd; st=\$?; echo; echo '[robot_dev] $title: process exited (code' \"\$st\" ')'; echo 'Press ENTER to close (or use robot_dev.sh stop)'; read -r" & disown
  elif [[ -n "${DISPLAY:-}" ]] && in_path xterm; then
    xterm -T "$title" -hold -e bash -lc "$cmd; st=\$?; echo; echo '[robot_dev] $title: process exited (code' \"\$st\" ')'; echo; read -r" & disown
  else
    nohup bash -lc "$cmd" >"/tmp/${title}.log" 2>&1 & disown
    log "start (bg): $title → /tmp/${title}.log"
  fi
}

cmd_broker_start() { log "start: broker";  exec python3 "$BROKER"; }
cmd_voice_start()  { log "start: voice";   exec python3 "$VOICE";  }
cmd_chat_start()   { log "start: chat";    exec python3 "$CHAT";   }

# UI — start w trybie FG; przejęcie ekranu przed startem
cmd_face_start() {
  log "start: face (UI)"
  kill_startup; kill_spi_holders
  : "${FACE_BACKEND:=lcd}"
  : "${FACE_GUIDE:=${FACE_GUIDE:-1}}"
  : "${FACE_BENCH:=${FACE_BENCH:-1}}"
  : "${FACE_HEAD_KY:=${FACE_HEAD_KY:-1.04}}"
  export FACE_BACKEND FACE_GUIDE FACE_BENCH FACE_HEAD_KY
  exec python3 "$FACE"
}

cmd_all() {
  log "start: all (broker, voice, chat?, face)"
  term "broker" "python3 '$BROKER'"
  sleep 0.3
  [[ -f "$VOICE" ]] && term "voice" "python3 '$VOICE'" || log "WARN: brak $VOICE"
  if [[ "${VOICE_STANDALONE:-1}" = "1" ]]; then
    log "VOICE_STANDALONE=1 → pomijam 'chat'"
  else
    [[ -f "$CHAT"  ]] && term "chat"  "python3 '$CHAT'"  || log "WARN: brak $CHAT"
  fi
  if [[ -n "${DISPLAY:-}" ]]; then
    if [[ -f "$FACE" ]]; then
      # takeover w tej samej powłoce (prosto → zero problemów z cytowaniem)
      kill_startup; kill_spi_holders
      term "face" "FACE_BACKEND='${FACE_BACKEND:-lcd}' FACE_GUIDE='${FACE_GUIDE:-1}' FACE_BENCH='${FACE_BENCH:-1}' FACE_HEAD_KY='${FACE_HEAD_KY:-1.04}' python3 '$FACE'"
    else
      log "WARN: brak UI (face)"
    fi
  else
    log "headless: DISPLAY unset → pomijam 'face'"
  fi
  log "tip: użyj 'robot_dev.sh status' aby sprawdzić porty/procesy"
}

cmd_stop() {
  log "stop: voice/chat/broker/face"
  if [[ -f "$PUB" ]]; then
    python3 "$PUB" control.stop '{}' 2>/dev/null || true
  fi
  kill_of "$VOICE"; kill_of "$CHAT"; kill_of "$BROKER"; kill_of "$FACE"
  sleep 0.3
  pkill -KILL -f "$VOICE"  2>/dev/null || true
  pkill -KILL -f "$CHAT"   2>/dev/null || true
  pkill -KILL -f "$BROKER" 2>/dev/null || true
  pkill -KILL -f "$FACE"   2>/dev/null || true
  # zamknij okna terminali
  pkill -f "lxterminal -t broker"  2>/dev/null || true
  pkill -f "lxterminal -t voice"   2>/dev/null || true
  pkill -f "lxterminal -t chat"    2>/dev/null || true
  pkill -f "lxterminal -t face"    2>/dev/null || true
  pkill -f "xterm -T broker"       2>/dev/null || true
  pkill -f "xterm -T voice"        2>/dev/null || true
  pkill -f "xterm -T chat"         2>/dev/null || true
  pkill -f "xterm -T face"         2>/dev/null || true
  log "stop: done"
}

cmd_status() {
  log "status:"
  echo "  ports: $(check_port "$BUS_PUB_PORT"), $(check_port "$BUS_SUB_PORT")"
  echo "  env:   BUS_PUB_PORT=${BUS_PUB_PORT}  BUS_SUB_PORT=${BUS_SUB_PORT}  VOICE_STANDALONE=${VOICE_STANDALONE:-1}  FACE_BACKEND=${FACE_BACKEND:-lcd}  FACE_HEAD_KY=${FACE_HEAD_KY:-1.04}  FACE_GUIDE=${FACE_GUIDE:-1}"
  echo "  broker:"; pids_of "$BROKER" | sed 's/^/    /' || true
  echo "  voice:";  pids_of "$VOICE"  | sed 's/^/    /' || true
  echo "  chat:";   pids_of "$CHAT"   | sed 's/^/    /' || true
  echo "  face:";   pids_of "$FACE"   | sed 's/^/    /' || true
}

cmd_restart() { cmd_stop; sleep 0.5; cmd_all; }

cmd_help() {
  cat <<'EOF'
Użycie:
  robot_dev.sh broker        # uruchom broker (FG)
  robot_dev.sh voice         # uruchom voice  (FG)
  robot_dev.sh chat          # uruchom chat   (FG)
  robot_dev.sh face          # UI (LCD/TK; honoruje FACE_* ENV)
  robot_dev.sh takeover      # przejęcie ekranu: pkill root-start app + zwolnij SPI
  robot_dev.sh all           # broker + voice + (chat gdy VOICE_STANDALONE=0) + face
  robot_dev.sh restart       # stop → all
  robot_dev.sh stop          # awaryjny STOP + ubij procesy + domknij okna
  robot_dev.sh status        # porty i procesy
  robot_dev.sh help          # to okno

Przydatne ENV dla face:
  FACE_BACKEND=lcd|tk   # domyślnie lcd (gdy DISPLAY brak → tk pomijany)
  FACE_GUIDE=0|1        # elipsa przewodnik
  FACE_HEAD_KY=1.04     # skala w pionie (0.90–1.20)
  FACE_BENCH=0|1        # log benchmarku
EOF
}

cmd="${1:-help}"
case "$cmd" in
  broker)    cmd_broker_start ;;
  voice)     cmd_voice_start  ;;
  chat)      cmd_chat_start   ;;
  face)      cmd_face_start   ;;
  takeover)  cmd_takeover_only;;
  all)       cmd_all          ;;
  restart)   cmd_restart      ;;
  stop)      cmd_stop         ;;
  status)    cmd_status       ;;
  help|-h|--help) cmd_help    ;;
  *) log "nieznane polecenie: $cmd"; cmd_help; exit 1 ;;
esac
