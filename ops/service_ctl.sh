#!/usr/bin/env bash
# ops/service_ctl.sh — bezpieczne sterowanie wybranymi usługami systemd (z logs)
# Użycie:
#   service_ctl.sh <alias|unit> <start|stop|restart|enable|disable|status|logs>
# Przykłady:
#   service_ctl.sh motion restart
#   service_ctl.sh api logs
#   LOG_LINES=200 service_ctl.sh broker logs

set -euo pipefail

SYSTEMCTL="$(command -v systemctl || echo /bin/systemctl)"
JOURNALCTL="$(command -v journalctl || echo /bin/journalctl)"
LOG_LINES="${LOG_LINES:-120}"

# --- Whitelist dozwolonych unitów ---
ALLOWED=(
  "rider-broker.service"
  "rider-api.service"
  "rider-motion-bridge.service"
  "rider-vision.service"
  "rider-ssd-preview.service"
)

usage(){
  echo "Usage: $0 <unit|alias> <start|stop|restart|enable|disable|status|logs>" >&2
  exit 2
}

map_alias(){
  case "${1:-}" in
    broker)  echo "rider-broker.service" ;;
    api)     echo "rider-api.service" ;;
    motion)  echo "rider-motion-bridge.service" ;;
    vision)  echo "rider-vision.service" ;;
    preview) echo "rider-ssd-preview.service" ;;
    *)       echo "${1:-}" ;;
  esac
}

normalize_unit(){
  local u="$1"
  [[ "$u" == *.* ]] || u+=".service"
  echo "$u"
}

is_allowed(){
  local want="$1"
  for u in "${ALLOWED[@]}"; do
    [[ "$u" == "$want" ]] && return 0
  done
  return 1
}

[[ $# -ge 2 ]] || usage
REQ_RAW="$1"; ACTION="$2"
UNIT_REQ="$(normalize_unit "$(map_alias "$REQ_RAW")")"

if ! is_allowed "$UNIT_REQ"; then
  echo "DENY: unit '$UNIT_REQ' not in whitelist" >&2
  exit 1
fi

case "$ACTION" in
  start|stop|restart|enable|disable)
    exec "$SYSTEMCTL" "$ACTION" "$UNIT_REQ"
    ;;
  status)
    "$SYSTEMCTL" show "$UNIT_REQ" --no-page \
      --property=Description,FragmentPath,UnitFileState,ActiveState,SubState,ExecStart,Environment
    ;;
  logs)
    # ostatnie N linii dziennika; można pipe'ować do grep/egrep
    exec "$JOURNALCTL" -u "$UNIT_REQ" -n "$LOG_LINES" --no-pager
    ;;
  *)
    usage ;;
esac
