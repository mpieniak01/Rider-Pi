#!/usr/bin/env bash
# Internal systemd executor. Called only by the authoritative API manager.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
export PYTHONPATH="${BASE_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
mapfile -t ALLOW_UNITS < <(python3 -m common.service_catalog units)
[[ ${#ALLOW_UNITS[@]} -gt 0 ]] || { echo "Catalog unavailable" >&2; exit 3; }
is_action() { case "$1" in start|stop|restart|enable|disable) return 0;; *) return 1;; esac; }
A="${1:-}"; B="${2:-}"
if is_action "$A"; then ACTION="$A"; UNIT="$B"
elif is_action "$B"; then UNIT="$A"; ACTION="$B"
else echo "Usage: $0 UNIT ACTION" >&2; exit 2; fi
allowed=0
for candidate in "${ALLOW_UNITS[@]}"; do [[ "$candidate" != "$UNIT" ]] || allowed=1; done
[[ $allowed -eq 1 ]] || { echo "Unit outside catalog" >&2; exit 3; }
python3 "${SCRIPT_DIR}/service-action-guard.py" "$UNIT" "$ACTION"
# Do not fall back to a different host/scope if the system manager rejects an action.
exec systemctl --no-pager "$ACTION" "$UNIT"
