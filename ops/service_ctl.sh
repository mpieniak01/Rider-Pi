#!/usr/bin/env bash
# ops/service_ctl.sh — bezpieczne sterowanie wybranymi usługami systemd
# Użycie:
#   service_ctl.sh <alias|unit> <start|stop|restart|enable|disable|status>
# Przykłady:
#   service_ctl.sh vision-hog start
#   service_ctl.sh preview restart
#   service_ctl.sh rider-vision.service status

set -euo pipefail

SYSTEMCTL="$(command -v systemctl || echo /bin/systemctl)"

# --- Whitelist dozwolonych unitów (TYLKO te mogą być kontrolowane) ---
# Dodaliśmy rider-vision-hog.service oraz rider-preview.service
ALLOWED=(
  "rider-vision.service"
  "rider-last-frame-sink.service"
  "rider-vision-hog.service"
  "rider-preview.service"
)

usage(){
  echo "Usage: $0 <unit|alias> <start|stop/|restart|enable|disable|status>" >&2
  exit 2
}

# Mapowanie aliasów na pełne nazwy unitów
map_alias(){
  case "${1:-}" in
    vision)               echo "rider-vision.service" ;;
    last|lastframe)       echo "rider-last-frame-sink.service" ;;
    preview)              echo "rider-preview.service" ;;
    vision-hog|hog|people)echo "rider-vision-hog.service" ;;
    *)                    echo "${1:-}" ;;
  esac
}

# Uzupełnij rozszerzenie .service kiedy ktoś poda skrót rider-foo bez kropki
normalize_unit(){
  local u="$1"
  [[ "$u" == *.* ]] || u+=".service"
  echo "$u"
}

[[ $# -ge 2 ]] || usage
REQ_RAW="$1"; ACTION="$2"
UNIT_REQ="$(map_alias "$REQ_RAW")"
UNIT_REQ="$(normalize_unit "$UNIT_REQ")"

is_allowed(){
  local want="$1"
  for u in "${ALLOWED[@]}"; do
    [[ "$u" == "$want" ]] && return 0
  done
  return 1
}

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
      --property=ActiveState,SubState,UnitFileState,LoadState,Description
    ;;
  *)
    usage ;;
esac

