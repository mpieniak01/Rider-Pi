#!/usr/bin/env bash
# Public vision goal; service membership is owned by the API catalog.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
case "${1:-}" in
 on) exec "${RIDER_PYTHON:-python3}" "$SCRIPT_DIR/robot_ctl.py" start s7_obstacle_module --options '{"provider":"local"}' "${@:2}";;
 off) exec "${RIDER_PYTHON:-python3}" "$SCRIPT_DIR/robot_ctl.py" stop s7_obstacle_module "${@:2}";;
 burst) exec "${RIDER_PYTHON:-python3}" "$SCRIPT_DIR/robot_ctl.py" start s7_obstacle_module --options '{"provider":"local"}' --seconds "${2:-120}" "${@:3}";;
 status) exec "${RIDER_PYTHON:-python3}" "$SCRIPT_DIR/robot_ctl.py" status "${@:2}";;
 *) echo "Usage: $0 {on|off|burst [seconds]|status}" >&2; exit 2;;
esac
