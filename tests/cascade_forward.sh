#!/usr/bin/env bash
set -euo pipefail
API=${API:-http://127.0.0.1:8080}
V0=${1:-0.12}
STEP=${2:-0.04}
N=${3:-6}
DUR=${4:-0.12}
GAP=${5:-0.12}

trap 'curl -fsS "$API/api/stop" >/dev/null 2>&1 || true' EXIT
v=$V0
for i in $(seq 1 "$N"); do
  curl -fsS -X POST "$API/api/control" -H 'Content-Type: application/json' \
    -d "{\"type\":\"drive\",\"vx\":$v,\"vy\":0,\"yaw\":0,\"dur\":$DUR}" >/dev/null
  sleep "$GAP"
  v=$(python3 - <<PY
v=$v+$STEP
print(round(v,3))
PY
)
done
