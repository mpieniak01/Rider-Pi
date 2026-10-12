#!/usr/bin/env bash
# Public alias: all service decisions use the serving API.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
A="${1:-}"; B="${2:-}"
case "$A" in start|stop|restart|enable|disable|status|logs) ACTION="$A"; UNIT="$B";; *) UNIT="$A"; ACTION="$B";; esac
exec "${RIDER_PYTHON:-python3}" "$SCRIPT_DIR/resource_ctl.py" service "$ACTION" "$UNIT" "${@:3}"
