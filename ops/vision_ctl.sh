#!/usr/bin/env bash
# Rider-Pi Vision Control Script
# Zarządzanie usługą vision: on/off/burst/status

set -euo pipefail

SERVICE="rider-vision.service"

cmd="${1:-}"

case "$cmd" in
  on)
    echo "[vision] starting $SERVICE"
    sudo systemctl unmask "$SERVICE" || true
    sudo systemctl start "$SERVICE"
    ;;
  off)
    echo "[vision] stopping $SERVICE"
    sudo systemctl stop "$SERVICE" || true
    ;;
  burst)
    secs="${2:-120}"
    echo "[vision] burst mode: running $SERVICE for ${secs}s"
    sudo systemctl unmask "$SERVICE" || true
    sudo systemctl restart "$SERVICE"
    (
      sleep "$secs"
      echo "[vision] burst finished → stopping $SERVICE"
      sudo systemctl stop "$SERVICE"
    ) >/dev/null 2>&1 &
    ;;
  status)
    systemctl --no-pager -l status "$SERVICE"
    ;;
  *)
    echo "Usage: $0 {on|off|burst [secs]|status}"
    exit 2
    ;;
esac
