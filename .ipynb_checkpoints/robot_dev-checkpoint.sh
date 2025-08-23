#!/usr/bin/env bash
# shellcheck disable=SC1090
# Dev helper do ręcznego uruchamiania i kontroli komponentów robota.
# Działa bez systemd; prosto start/stop/status, bez niespodzianek.

set -Eeuo pipefail
IFS=$'\n\t'
LANG=C.UTF-8

ROOT="/home/pi/robot"
VOICE="${ROOT}/apps/voice/main.py"
CHAT="${ROOT}/apps/chat/main.py"
BROKER="${ROOT}/scripts/broker.py"

# --- LOG + bezpieczne źródła -------------------------------------------------
log() { printf "[%(%H:%M:%S)T] %s\n" -1 "$*"; }

# Miękkie wczytanie profilu, żeby nie wysypywać się na nieustawionych zmiennych
if [[ -f "$HOME/.bash_profile" ]]; then
  set +u
  . "$HOME/.bash_profile" >/dev/null 2>&1 || true
  set -u
fi

# PYTHONPATH odporne na brak zmiennej
export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"

# --- Narzędzia ---------------------------------------------------------------
in_path() { command -v "$1" >/dev/null 2>&1; }

pids_of() {
  # szukaj procesów python uruchomionych na wskazanym pliku
  pgrep -fa python3 | grep -F "$1" || true
}

kill_of() {
  local what="${1:-}"
  [[ -z "$what" ]] && return 0
  # zabij tylko konkretne skrypty (ostrożnie z grep)
  pgrep -f "$what" >/dev/null 2>&1 || return 0
  pkill -TERM -f "$what" || true
}

check_port() {
  local port="$1"
  (ss -ltpn 2>/dev/null | grep -q ":${port} ") && echo "LISTEN:${port}" || echo "free:${port}"
}

# --- Komendy uruchomieniowe --------------------------------------------------
cmd_broker_start() {
  log "start: broker"
  exec python3 "$BROKER"
}

cmd_voice_start() {
  log "start: voice"
  exec python3 "$VOICE"
}

cmd_chat_start() {
  log "start: chat"
  exec python3 "$CHAT"
}

cmd_stop() {
  log "stop: voice/chat/broker"
  kill_of "$VOICE"
  kill_of "$CHAT"
  kill_of "$BROKER"
  sleep 0.3
  # dokończ siłowo, jeśli coś się ostało
  pkill -KILL -f "$VOICE" 2>/dev/null || true
  pkill -KILL -f "$CHAT"  2>/dev/null || true
  pkill -KILL -f "$BROKER" 2>/dev/null || true
  log "stop: done"
}

cmd_status() {
  log "status:"
  echo "  ports: $(check_port 5555), $(check_port 5556)"
  echo "  broker:"
  pids_of "$BROKER" | sed 's/^/    /' || true
  echo "  voice:"
  pids_of "$VOICE" | sed 's/^/    /' || true
  echo "  chat:"
  pids_of "$CHAT" | sed 's/^/    /' || true
}

cmd_help() {
  cat <<'EOF'
Użycie:
  robot_dev.sh broker     # uruchom broker w tym terminalu (FG)
  robot_dev.sh voice      # uruchom voice w tym terminalu (FG)
  robot_dev.sh chat       # uruchom chat w tym terminalu (FG)
  robot_dev.sh stop       # zatrzymaj wszystkie trzy
  robot_dev.sh status     # pokaż porty i procesy
  robot_dev.sh help       # to okno
Wskazówka: odpal każdy moduł w osobnej konsoli (FG), żeby mieć logi na żywo.
EOF
}

# --- Router poleceń ----------------------------------------------------------
cmd="${1:-help}"
case "$cmd" in
  broker)  cmd_broker_start ;;
  voice)   cmd_voice_start ;;
  chat)    cmd_chat_start ;;
  stop)    cmd_stop ;;
  status)  cmd_status ;;
  help|-h|--help) cmd_help ;;
  *) log "nieznane polecenie: $cmd"; cmd_help; exit 1 ;;
esac
