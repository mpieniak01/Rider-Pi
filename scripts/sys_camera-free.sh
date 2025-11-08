#!/usr/bin/env bash
# Zwolnienie /dev/video* i opcjonalnie SPI przez selektywne zabijanie PID-ów.

set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --device PATH        Główne urządzenie V4L2 (domyślnie /dev/video0)
  --extra PATH         Dodatkowe urządzenie do sprawdzenia (można powtarzać)
  --with-spi           Automatycznie dodaj /dev/spidev0.0 i /dev/spidev0.1
  --pid PID            Ogranicz działanie do konkretnego PID (można powtarzać)
  --help               Wyświetl pomoc
EOF
}

DEVICES=("/dev/video0")
LIMIT_PIDS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device)
      DEVICES=("$2")
      shift 2
      ;;
    --extra)
      DEVICES+=("$2")
      shift 2
      ;;
    --with-spi)
      DEVICES+=("/dev/spidev0.0" "/dev/spidev0.1")
      shift
      ;;
    --pid)
      LIMIT_PIDS+=("$2")
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

log() { echo "[camera-free] $*" >&2; }

collect_pids() {
  local dev
  declare -A seen=()
  for dev in "${DEVICES[@]}"; do
    [[ -e "$dev" ]] || continue
    local listing
    listing=$(fuser "$dev" 2>/dev/null || sudo -n fuser "$dev" 2>/dev/null || true)
    for pid in $listing; do
      [[ -n "$pid" ]] || continue
      seen[$pid]=1
    done
  done
  for pid in "${!seen[@]}"; do
    echo "$pid"
  done
}

should_handle_pid() {
  local pid="$1"
  if [[ ${#LIMIT_PIDS[@]} -eq 0 ]]; then
    return 0
  fi
  local limit
  for limit in "${LIMIT_PIDS[@]}"; do
    if [[ "$limit" == "$pid" ]]; then
      return 0
    fi
  done
  return 1
}

kill_pid() {
  local pid="$1"
  if ! should_handle_pid "$pid"; then
    return 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  log "Sending SIGTERM to PID=$pid"
  kill -TERM "$pid" 2>/dev/null || true
  for _ in {1..10}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.1
  done
  log "PID=$pid still alive, sending SIGKILL"
  kill -KILL "$pid" 2>/dev/null || true
}

main() {
  local pids pid handled=0
  mapfile -t pids < <(collect_pids)
  if [[ ${#pids[@]} -eq 0 ]]; then
    log "Brak blokujących procesów"
    return 0
  fi
  for pid in "${pids[@]}"; do
    [[ -n "$pid" ]] || continue
    if kill_pid "$pid"; then
      handled=$((handled + 1))
    fi
  done
  log "Obsłużono $handled procesów"
}

main "$@"
