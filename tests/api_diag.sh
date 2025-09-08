#!/usr/bin/env bash
# robot/tests/api_diag.sh
# Uniwersalny skrypt diagnostyczny API (dev run + testy)
# Zależności: bash, curl, (opcjonalnie jq, lsof)
set -euo pipefail

# ── Konfiguracja domyślna ──────────────────────────────────────────────────────
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_FILE="$ROOT_DIR/services/api_server.py"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8080}"
BASE="http://${API_HOST}:${API_PORT}"
JQ_BIN="${JQ:-jq}"          # ustaw JQ=cat jeśli nie masz jq
CURL="curl -fsS"
TIMEFMT='time_connect=%{time_connect} time_starttransfer=%{time_starttransfer} total=%{time_total}\n'

# wykryj jq
if [[ "$JQ_BIN" = "jq" ]] && command -v jq >/dev/null 2>&1; then
  HAS_JQ=1
else
  HAS_JQ=0
  JQ_BIN="cat"
fi

usage() {
  cat <<EOF
api_diag.sh — skrypt diagnostyczny Rider-Pi API

Użycie:
  $(basename "$0") start         # uruchom API w trybie dev (foreground)
  $(basename "$0") stop          # ubij proces nasłuchujący na porcie (miękko)
  $(basename "$0") smoke         # szybkie sprawdzenie /healthz, /readyz, /api/status...
  $(basename "$0") flags         # cykl flag: motion.enable i estop.on (on/off)
  $(basename "$0") latency [N]   # pomiar czasu dla /api/status (domyślnie N=20)
  $(basename "$0") stress [N]    # N pętli GET (healthz + metrics), domyślnie N=200
  $(basename "$0") lastframe     # meta-informacja o data/last_frame.jpg
  $(basename "$0") all           # smoke → flags → latency(20) → lastframe

Zmienne środowiskowe:
  API_HOST (domyślnie 127.0.0.1), API_PORT (8080), JQ (jq|cat)
EOF
}

need_api_file() {
  [[ -f "$API_FILE" ]] || { echo "[ERR] Nie znaleziono $API_FILE" >&2; exit 1; }
}

kill_by_port() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -ti tcp:$port || true)"
    if [[ -n "${pids:-}" ]]; then
      echo "[stop] killing PIDs: $pids (port $port)"
      kill $pids || true
    else
      echo "[stop] nothing on port $port"
    fi
  else
    echo "[WARN] lsof nie dostępny — pomiń 'stop' albo zainstaluj lsof."
  fi
}

start_api() {
  need_api_file
  export API_HOST API_PORT API_DEBUG=${API_DEBUG:-0}
  echo "[run] $API_FILE on ${API_HOST}:${API_PORT}"
  exec python3 -u "$API_FILE"
}

stop_api() {
  kill_by_port "$API_PORT"
}

# helpery jq (bezpieczne przy braku jq)
pp() {  # pretty print JSON jeśli jq dostępny
  if [[ $HAS_JQ -eq 1 ]]; then jq .; else cat; fi
}
jq_filter() {  # wyciągnięcie fragmentu .foo.bar jeśli jq dostępny
  local filter="${1:-.}"
  if [[ $HAS_JQ -eq 1 ]]; then jq "$filter"; else cat; fi
}
jq_get_raw() { # .path -> wartość; zwraca pusty string bez jq
  local filter="${1:-.}"
  if [[ $HAS_JQ -eq 1 ]]; then jq -r "$filter"; else cat >/dev/null; fi
}

smoke() {
  echo "# healthz";           $CURL "$BASE/healthz"            | pp
  echo "# readyz";            $CURL "$BASE/readyz"             | pp
  echo "# livez";             $CURL "$BASE/livez"              | pp
  echo "# version";           $CURL "$BASE/api/version"        | pp
  echo "# bus_health";        $CURL "$BASE/api/bus/health"     | pp
  echo "# status";            $CURL "$BASE/api/status"         | jq_filter '.system.cpu, .devices.summary.flags'
  echo "# metrics (json)";    $CURL "$BASE/api/metrics"        | jq_filter '.cpu, .mem, .load, .uptime'
  echo "# devices";           $CURL "$BASE/api/devices"        | pp
  echo "# last_frame";        $CURL "$BASE/api/last_frame"     | pp
}

flags_cycle() {
  echo "== before ==";            $CURL "$BASE/api/flags" | pp
  echo "== enable motion ==";     $CURL -X POST "$BASE/api/flags/motion.enable/on" | pp
                                  $CURL "$BASE/api/flags" | pp
  echo "== estop on ==";          $CURL -X POST "$BASE/api/flags/estop.on/on" | pp
                                  $CURL "$BASE/api/flags" | pp
  echo "== cleanup ==";           $CURL -X POST "$BASE/api/flags/estop.on/off" | pp
                                  $CURL -X POST "$BASE/api/flags/motion.enable/off" | pp
                                  $CURL "$BASE/api/flags" | pp
}

latency() {
  local n="${1:-20}"
  echo "# measuring $n requests to $BASE/api/status"
  for i in $(seq 1 "$n"); do
    curl -o /dev/null -sS -w "$TIMEFMT" "$BASE/api/status"
  done
}

stress() {
  local n="${1:-200}"
  echo "# stress $n loops (healthz + metrics)"
  for i in $(seq 1 $n); do
    $CURL "$BASE/healthz" >/dev/null
    $CURL "$BASE/api/metrics" >/dev/null
  done
  echo "done: $n*2 requests"
}

lastframe() {
  local meta path
  meta="$($CURL "$BASE/api/last_frame")"
  echo "$meta" | pp
  if [[ $HAS_JQ -eq 1 ]]; then
    path="$(echo "$meta" | jq -r '.path // empty')"
  else
    path=""
  fi
  if [[ -n "${path:-}" && -f "$path" ]]; then
    local mtime
    if stat --version >/dev/null 2>&1; then
      mtime="$(stat -c %Y "$path")"
    else
      mtime="$(stat -f %m "$path")"  # macOS
    fi
    echo "last_frame exists: $path (mtime=$mtime)"
  else
    echo "last_frame missing or path not provided."
  fi
}

all() {
  smoke
  flags_cycle
  latency 20
  lastframe
}

cmd="${1:-help}"
case "$cmd" in
  start)     start_api ;;
  stop)      stop_api ;;
  smoke)     smoke ;;
  flags)     flags_cycle ;;
  latency)   shift || true; latency "${1:-}" ;;
  stress)    shift || true; stress "${1:-}" ;;
  lastframe) lastframe ;;
  all)       all ;;
  help|-h|--help) usage ;;
  *) echo "[ERR] Nieznana komenda: $cmd"; echo; usage; exit 2 ;;
esac
