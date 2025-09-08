#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-127.0.0.1:8081}"
BASE="http://${HOST}"
HDR='Content-Type: application/json'

# Parametry bezpieczeństwa (możesz nadpisać ENV)
VX="${VX:-0.10}"         # 0..1 (lekko)
DUR="${DUR:-0.12}"       # s (krótki impuls)
PAUSE="${PAUSE:-0.30}"   # s między impulsami

echo "== Smoke: healthz @ ${BASE}/healthz =="
curl -sf "${BASE}/healthz" | sed -e 's/^/  /'

echo
echo "== Smoke: GET powinno zwrócić 405 (test kontraktu) =="
set +e
curl -s -o /dev/null -w "%{http_code}\n" "${BASE}/api/move?dir=forward" | grep -q '^405$' && echo "  OK 405"
curl -s -o /dev/null -w "%{http_code}\n" "${BASE}/api/stop"           | grep -q '^405$' && echo "  OK 405"
set -e

echo
echo "== SAFE: POST move forward (mikro-impuls) =="
curl -sf -X POST "${BASE}/api/move" -H "$HDR" \
  -d "{\"vx\": ${VX}, \"vy\": 0, \"yaw\": 0, \"duration\": ${DUR}}" | sed -e 's/^/  /'
sleep 0.05
curl -sf -X POST "${BASE}/api/stop" | sed -e 's/^/  /'
sleep "${PAUSE}"

echo
echo "== SAFE: POST move backward (mikro-impuls) =="
curl -sf -X POST "${BASE}/api/move" -H "$HDR" \
  -d "{\"vx\": -${VX}, \"vy\": 0, \"yaw\": 0, \"duration\": ${DUR}}" | sed -e 's/^/  /'
sleep 0.05
curl -sf -X POST "${BASE}/api/stop" | sed -e 's/^/  /'

echo
echo "== Opcjonalnie: /api/balance on/off =="
set +e
curl -s -X GET "${BASE}/api/balance?on=1" | sed -e 's/^/  /'
curl -s -X GET "${BASE}/api/balance?on=0" | sed -e 's/^/  /'
set -e

echo
echo "== Opcjonalnie: /api/height?h=30 =="
set +e
curl -s -X GET "${BASE}/api/height?h=30" | sed -e 's/^/  /'
set -e

echo
echo "OK (SAFE) ✅"
