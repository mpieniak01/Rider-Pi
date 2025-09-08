#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-127.0.0.1:8081}"
BASE="http://${HOST}"
HDR='Content-Type: application/json'
OUTDIR="${OUTDIR:-$HOME/robot/tests/out}"
mkdir -p "$OUTDIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="${OUTDIR}/diag-${STAMP}.log"

# Parametry bezpieczeństwa
VX="${VX:-0.10}"
DUR="${DUR:-0.12}"
PAUSE="${PAUSE:-0.30}"

{
  echo "== healthz =="
  curl -sf "${BASE}/healthz"; echo

  echo
  echo "== SAFE forward micro =="
  curl -sf -X POST "${BASE}/api/move" -H "$HDR" -d "{\"vx\": ${VX},  \"vy\":0, \"yaw\":0, \"duration\": ${DUR}}"; echo
  sleep 0.05
  curl -sf -X POST "${BASE}/api/stop"; echo
  sleep "${PAUSE}"

  echo
  echo "== SAFE backward micro =="
  curl -sf -X POST "${BASE}/api/move" -H "$HDR" -d "{\"vx\": -${VX}, \"vy\":0, \"yaw\":0, \"duration\": ${DUR}}"; echo
  sleep 0.05
  curl -sf -X POST "${BASE}/api/stop"; echo

  echo
  echo "== balance on/off (best-effort) =="
  curl -s "${BASE}/api/balance?on=1"; echo
  curl -s "${BASE}/api/balance?on=0"; echo

  echo
  echo "== height 30 (best-effort) =="
  curl -s "${BASE}/api/height?h=30"; echo

  echo
  echo "== ostatnie logi bridge =="
  journalctl -u rider-motion-bridge.service -n 120 --no-pager || true

  echo
  echo "== ostatnie logi web-bridge =="
  journalctl -u rider-web-bridge.service -n 120 --no-pager || true

} | tee "$LOG" >/dev/null

echo "Diag zapisano w: $LOG"
