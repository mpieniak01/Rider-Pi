#!/usr/bin/env bash
set -euo pipefail

BUS_PUB_PORT="${BUS_PUB_PORT:-5555}"
BUS_SUB_PORT="${BUS_SUB_PORT:-5556}"
STATUS_API_PORT="${STATUS_API_PORT:-8080}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_BROKER="/tmp/broker.log"
LOG_API="/tmp/api.log"
LOG_BRIDGE="/tmp/bridge.log"

say(){ printf "\033[1;36m==> %s\033[0m\n" "$*"; }
fail(){ printf "\033[1;31mFAIL:\033[0m %s\n" "$*" >&2; exit 1; }
pass(){ printf "\033[1;32mPASS:\033[0m %s\n" "$*\n"; }

cd "$ROOT"
set +o noclobber || true
pkill -f scripts/status_api.py || true
pkill -f scripts/motion_bridge.py || true
pkill -f scripts/broker.py || true
sudo fuser -k ${BUS_PUB_PORT}/tcp ${BUS_SUB_PORT}/tcp || true
rm -f "$LOG_BROKER" "$LOG_API" "$LOG_BRIDGE"

say "Start broker"
nohup python3 scripts/broker.py >> "$LOG_BROKER" 2>&1 &
say "Start API"
nohup python3 scripts/status_api.py >> "$LOG_API" 2>&1 &
say "Start motion_bridge (DRY_RUN=1)"
nohup env DRY_RUN=1 SPEED_LINEAR=12 SPEED_TURN=20 \
  python3 scripts/motion_bridge.py >> "$LOG_BRIDGE" 2>&1 &

# Czekamy aż porty się zbindowały
say "Wait for ports"
for i in {1..20}; do
  if sudo fuser ${BUS_PUB_PORT}/tcp >/dev/null 2>&1 && sudo fuser ${BUS_SUB_PORT}/tcp >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

# Czekamy aż bridge zaloguje START
say "Wait for bridge START"
for i in {1..25}; do
  grep -q "\[bridge] START" "$LOG_BRIDGE" && break || true
  sleep 0.2
done

# Dajemy XPUB/XSUB 1–2 s na propagację subskrypcji
sleep 1.5

say "Healthz"
curl -fsS "http://localhost:${STATUS_API_PORT}/healthz" >/dev/null || fail "/healthz not OK"

say "Move forward 0.7 for 0.8s"
curl -fsS -X POST "http://localhost:${STATUS_API_PORT}/api/move" \
  -H 'Content-Type: application/json' \
  -d '{"vx":0.7,"vy":0,"yaw":0,"duration":0.8}' >/dev/null || fail "move API failed"
sleep 1
say "Stop"
curl -fsS -X POST "http://localhost:${STATUS_API_PORT}/api/stop" \
  -H 'Content-Type: application/json' -d '{}' >/dev/null || fail "stop API failed"

say "Check bridge logs"
tail -n 200 "$LOG_BRIDGE" | grep -E "\[bridge] forward speed=[0-9]+\.[0-9]{2} t=0\.80" \
  || tail -n 200 "$LOG_BRIDGE" | grep -q "\[bridge] forward:" \
  || fail "no forward in bridge log"

tail -n 200 "$LOG_BRIDGE" | grep -q "\[bridge] stop" || fail "no stop in bridge log"

pass "REST → bus → bridge OK"
echo
echo "--- broker ---"; tail -n 20 "$LOG_BROKER" || true
echo "--- api    ---"; tail -n 20 "$LOG_API" || true
echo "--- bridge ---"; tail -n 20 "$LOG_BRIDGE" || true
