#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-127.0.0.1:8081}"
COUNT="${2:-50}"
DELAY="${3:-0.10}"
METHOD_LOWER="$(echo "${4:-post}" | tr '[:upper:]' '[:lower:]')"

BASE="http://${HOST}"
HDR='Content-Type: application/json'
# Bezpieczeństwo
VX="${VX:-0.10}"
DUR="${DUR:-0.10}"

case "$METHOD_LOWER" in
  post) METHOD="POST" ;;
  auto) METHOD="POST" ;;   # GET już nieobsługiwany → zawsze POST
  *)    METHOD="POST" ;;
esac

echo "== Burst: ${COUNT} komend, pauza ${DELAY}s, metoda ${METHOD} @ ${BASE} =="
ok=0; fail=0

for i in $(seq 1 "${COUNT}"); do
  # Naprzemiennie +VX (przód), -VX (tył) → robot oscyluje w miejscu
  if (( i % 2 == 1 )); then
    VXS="${VX}"
  else
    VXS="-$VX"
  fi

  if curl -sf -X "${METHOD}" "${BASE}/api/move" -H "$HDR" \
        -d "{\"vx\": ${VXS}, \"vy\": 0, \"yaw\": 0, \"duration\": ${DUR}}" >/dev/null; then
    ((ok++))
    printf "."
  else
    ((fail++))
    printf "X"
  fi

  sleep 0.05
  curl -s -X "${METHOD}" "${BASE}/api/stop" >/dev/null || true
  sleep "${DELAY}"
done
echo

echo "== Stop na końcu =="
curl -s -X "${METHOD}" "${BASE}/api/stop" >/dev/null || true

if (( fail == 0 )); then
  echo "OK (SAFE) ✅"
else
  echo "Skończone z błędami: ok=${ok}, fail=${fail} ❗"
  exit 1
fi
