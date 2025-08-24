#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# run_boot.sh — szybki rozruch po restarcie (broker → face), bez systemd.
# Działa zarówno z poziomu ./run_boot.sh (root projektu), jak i ./scripts/run_boot.sh
#
# Użycie:
#   ./run_boot.sh           # broker + face (LCD)
#   ./run_boot.sh --test    # + sekwencja smoke-test
#   ./run_boot.sh --tk      # zamiast LCD odpala wersję Tk (desktop)
#   ./run_boot.sh --stop    # zatrzymanie
# ──────────────────────────────────────────────────────────────────────────────
set -Eeuo pipefail
IFS=$'\n\t'
LANG=C.UTF-8

# ── Autodetekcja ROOT projektu ────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT=""
for candidate in "$SCRIPT_DIR" "$SCRIPT_DIR/.." "$SCRIPT_DIR/../.."; do
  if [[ -f "$candidate/scripts/broker.py" && -d "$candidate/apps/ui" ]]; then
    ROOT="$(cd "$candidate" && pwd)"; break
  fi
done
: "${ROOT:="$SCRIPT_DIR"}"
cd "$ROOT"

# ── ENV wspólne ───────────────────────────────────────────────────────────────
export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"
if [[ -f "${ROOT}/.env" ]]; then
  set +u; set -a; . "${ROOT}/.env"; set +a; set -u
fi
BUS_PUB_PORT="${BUS_PUB_PORT:-5555}"
BUS_SUB_PORT="${BUS_SUB_PORT:-5556}"

# ── domyślne FACE (możesz nadpisać w .env) ───────────────────────────────────
export FACE_BACKEND="${FACE_BACKEND:-lcd}"     # lcd|tk|auto
export FACE_BENCH="${FACE_BENCH:-1}"
export FACE_GUIDE="${FACE_GUIDE:-1}"
export FACE_LCD_ROTATE="${FACE_LCD_ROTATE:-270}"
export FACE_LCD_DO_INIT="${FACE_LCD_DO_INIT:-1}"
export FACE_HEAD_KY="${FACE_HEAD_KY:-1.04}"
export FACE_BROW_STYLE="${FACE_BROW_STYLE:-classic}"   # classic|tapered
export FACE_QUALITY="${FACE_QUALITY:-fast}"            # fast|aa2x
export FACE_BROW_TAPER="${FACE_BROW_TAPER:-0.5}"
export FACE_BROW_YK="${FACE_BROW_YK:-0.22}"
export FACE_BROW_HK="${FACE_BROW_HK:-0.09}"
export FACE_MOUTH_YK="${FACE_MOUTH_YK:-0.205}"

BROKER="${ROOT}/scripts/broker.py"
PUB="${ROOT}/scripts/pub.py"

log(){ printf "[%(%H:%M:%S)T] %s\n" -1 "$*"; }
have(){ command -v "$1" >/dev/null 2>&1; }

stop_all(){
  log "STOP: zatrzymuję face/broker"
  pkill -f "python3 -m apps.ui.face" 2>/dev/null || true
  pkill -f "/apps/ui/face.py"        2>/dev/null || true
  pkill -f "${BROKER}"               2>/dev/null || true
  sleep 0.3
  pkill -KILL -f "apps.ui.face|${BROKER}" 2>/dev/null || true
  log "STOP: OK"
}

kill_spi_holders(){
  log "SPI takeover: ubijam trzymaczy SPI (rootowa appka itp.)"
  sudo pkill -f "python3 remix.py" 2>/dev/null || true
  sudo pkill -f "mian.py|main.py|demo.*.py|app_.*.py" 2>/dev/null || true
}

start_broker(){
  if ss -ltpn 2>/dev/null | grep -q ":${BUS_PUB_PORT} "; then
    log "broker: już słucha na :${BUS_PUB_PORT}"
    return 0
  fi
  log "start: broker (PUB=${BUS_PUB_PORT} SUB=${BUS_SUB_PORT})"
  if [[ -n "${DISPLAY:-}" ]] && have lxterminal; then
    lxterminal -t "broker" -e bash -lc "python3 '${BROKER}'; echo; echo '[broker] exited'; read -r" & disown
  else
    nohup python3 "${BROKER}" > /tmp/broker.log 2>&1 & disown
    log "broker → /tmp/broker.log"
  fi
  for _ in {1..30}; do
    ss -ltpn 2>/dev/null | grep -q ":${BUS_PUB_PORT} " && break
    sleep 0.2
  done
}

start_face(){
  local backend="$1"   # lcd|tk
  log "start: face (backend=${backend})"
  if [[ -n "${DISPLAY:-}" ]] && have lxterminal; then
    FACE_BACKEND="${backend}" lxterminal -t "face" -e bash -lc "python3 -m apps.ui.face; echo; echo '[face] exited'; read -r" & disown
  else
    nohup env FACE_BACKEND="${backend}" python3 -m apps.ui.face > /tmp/face.log 2>&1 & disown
    log "face → /tmp/face.log"
  fi
}

smoke_test(){
  log "smoke-test: mimika przez bus"
  python3 "${PUB}" ui.face.set   '{"expr":"neutral"}'
  sleep 0.4
  python3 "${PUB}" ui.face.set   '{"expr":"happy","intensity":1,"blink":true}'
  sleep 0.6
  python3 "${PUB}" ui.face.config '{"brow_style":"tapered","quality":"aa2x","brow_taper":0.6}'
  sleep 0.4
  python3 "${PUB}" ui.face.set   '{"expr":"process"}'
  sleep 0.4
  python3 "${PUB}" ui.face.set   '{"expr":"low_battery"}'
  log "smoke-test: DONE"
}

# ── parse args ────────────────────────────────────────────────────────────────
DO_TEST=0; USE_TK=0; DO_STOP=0
for a in "$@"; do
  case "$a" in
    --test) DO_TEST=1 ;;
    --tk)   USE_TK=1 ;;
    --stop) DO_STOP=1 ;;
    *) log "Ignoruję nieznany argument: $a" ;;
  esac
done

if (( DO_STOP )); then
  stop_all; exit 0
fi

# ── run ───────────────────────────────────────────────────────────────────────
kill_spi_holders
start_broker
start_face "$([[ $USE_TK -eq 1 ]] && echo tk || echo lcd)"

sleep 1.2
if (( DO_TEST )); then
  smoke_test
fi

log "READY ✔  (broker+face).  Tip: ./run_boot.sh --test aby zobaczyć sekwencję."
