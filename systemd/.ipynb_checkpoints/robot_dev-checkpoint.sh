#!/usr/bin/env bash
# Simple runner for robot services (broker / voice / chat)
# No systemd, manual start/stop/status/logs.
# Usage:
#   ./run.sh start [all|broker|voice|chat]
#   ./run.sh stop  [all|broker|voice|chat]
#   ./run.sh restart [all|broker|voice|chat]
#   ./run.sh status
#   ./run.sh logs
set -euo pipefail

PROJECT_ROOT="/home/pi/robot"
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"

# Load env (API key etc.)
if [ -f "$HOME/.bash_profile" ]; then
  # silence output from sourcing
  # shellcheck disable=SC1090
  source "$HOME/.bash_profile" >/dev/null 2>&1 || true
fi

export PYTHONPATH="$PROJECT_ROOT:${PYTHONPATH:-}"

# Defaults (you can override when calling, e.g. HOTWORD_THRESHOLD=0.6 ./run.sh start voice)
export ALSA_DEVICE="${ALSA_DEVICE:-plughw:1,0}"
export VOICE_STANDALONE="${VOICE_STANDALONE:-0}"
export HOTWORD_THRESHOLD="${HOTWORD_THRESHOLD:-0.58}"
export EXTRACTOR_GAIN="${EXTRACTOR_GAIN:-1.0}"
export HOTWORD_MIN_HITS="${HOTWORD_MIN_HITS:-1}"
export HIT_WINDOW_FRAMES="${HIT_WINDOW_FRAMES:-2}"
export REARM_SILENCE_DBFS="${REARM_SILENCE_DBFS:-99}"
export REARM_SILENCE_MS="${REARM_SILENCE_MS:-50}"

# Line-buffer Python stdout
PY="stdbuf -oL -eL /usr/bin/python3 -u"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

is_running() { pgrep -f "$1" >/dev/null 2>&1; }
kill_pattern() { pkill -f "$1" >/dev/null 2>&1 || true; }

port_busy() { ss -ltn | awk '{print $4}' | grep -q ":$1\$"; }

start_broker() {
  if is_running "/home/pi/robot/scripts/broker.py"; then
    log "broker already running"; return 0
  fi
  if port_busy 5556 || port_busy 5557; then
    log "broker ports busy (5556/5557) - maybe broker already running"; return 0
  fi
  log "starting broker..."
  nohup $PY /home/pi/robot/scripts/broker.py \
    >"$LOG_DIR/broker.log" 2>&1 &
  sleep 0.3
  log "broker log: tail -f $LOG_DIR/broker.log"
}

start_voice() {
  if is_running "/home/pi/robot/apps/voice/main.py"; then
    log "voice already running"; return 0
  fi
  log "starting voice..."
  nohup $PY /home/pi/robot/apps/voice/main.py \
    >"$LOG_DIR/voice.log" 2>&1 &
  sleep 0.4
  log "voice log: tail -f $LOG_DIR/voice.log"
}

start_chat() {
  if is_running "/home/pi/robot/apps/chat/main.py"; then
    log "chat already running"; return 0
  fi
  log "starting chat..."
  nohup $PY /home/pi/robot/apps/chat/main.py \
    >"$LOG_DIR/chat.log" 2>&1 &
  sleep 0.4
  log "chat log: tail -f $LOG_DIR/chat.log"
}

stop_broker() { log "stopping broker"; kill_pattern "/home/pi/robot/scripts/broker.py"; }
stop_voice()  { log "stopping voice";  kill_pattern "/home/pi/robot/apps/voice/main.py"; }
stop_chat()   { log "stopping chat";   kill_pattern "/home/pi/robot/apps/chat/main.py"; }

status_one() {
  name="$1"; pat="$2"
  if is_running "$pat"; then
    pids=$(pgrep -f "$pat" | tr '\n' ' ')
    log "$name: RUNNING (PIDs: $pids)"
  else
    log "$name: stopped"
  fi
}

status_all() {
  status_one "broker" "/home/pi/robot/scripts/broker.py"
  status_one "voice"  "/home/pi/robot/apps/voice/main.py"
  status_one "chat"   "/home/pi/robot/apps/chat/main.py"
  if port_busy 5556 || port_busy 5557; then
    log "ports 5556/5557: busy (broker likely running)"
  else
    log "ports 5556/5557: free"
  fi
}

logs_all() {
  log "tailing logs (ctrl+c to stop)"
  touch "$LOG_DIR"/{broker,voice,chat}.log
  tail -n 100 -F "$LOG_DIR"/broker.log "$LOG_DIR"/voice.log "$LOG_DIR"/chat.log
}

case "${1:-}" in
  start)
    what="${2:-all}"
    case "$what" in
      all)   start_broker; start_voice; start_chat ;;
      broker) start_broker ;;
      voice)  start_voice ;;
      chat)   start_chat ;;
      *) log "unknown service: $what"; exit 1 ;;
    esac
    ;;
  stop)
    what="${2:-all}"
    case "$what" in
      all)   stop_voice; stop_chat; stop_broker ;;
      broker) stop_broker ;;
      voice)  stop_voice ;;
      chat)   stop_chat ;;
      *) log "unknown service: $what"; exit 1 ;;
    esac
    ;;
  restart)
    what="${2:-all}"
    "$0" stop "$what"
    sleep 0.6
    "$0" start "$what"
    ;;
  status)
    status_all
    ;;
  logs)
    logs_all
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs} [all|broker|voice|chat]"
    exit 1
    ;;
esac
