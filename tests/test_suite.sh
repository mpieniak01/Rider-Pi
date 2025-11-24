#!/usr/bin/env bash
# Zintegrowany test E2E (przygotowanie, burst, podsumowanie).
# Wszystkie artefakty trafiają do ./out/
# Użycie: ./test_suite.sh [HOST:PORT]   # domyślnie 127.0.0.1:8080
set -euo pipefail
HOSTPORT="${1:-127.0.0.1:8080}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${DIR}/out"; mkdir -p "$OUT_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
LOG="${OUT_DIR}/suite-${TS}.log"
BASE="http://${HOSTPORT}"

say(){ printf "\n==> %s\n" "$*"; echo -e "\n==> $*" >>"$LOG"; }
run(){ echo "$ $*" | tee -a "$LOG"; eval "$@" 2>&1 | tee -a "$LOG"; }

say "Flagi ruchu (enable)"
run mkdir -p ~/robot/data/flags
run touch ~/robot/data/flags/motion.enable
run rm -f  ~/robot/data/flags/estop.on

say "Health checks"
run curl -fsS "$BASE/api/version" || true
run curl -fsS "$BASE/api/bus/health" || true

say "Burst 2x30 klików (0.12s)"
"$DIR/burst_web_moves.sh" "$HOSTPORT" 30 0.12 | tee -a "$LOG"

say "Podsumowanie od 2 min"
"$DIR/count_rx_since.sh" "2 minutes ago" | tee -a "$LOG"

feature_check() {
  local expect="$1"
  local feature="$2"
  python3 - "$BASE" "$feature" "$expect" <<'PY'
import json, sys, urllib.request

base, feature, expect = sys.argv[1:4]
resp = urllib.request.urlopen(f"{base}/api/logic/summary", timeout=5)
data = json.loads(resp.read().decode("utf-8"))
summary = (data or {}).get("summary", {})
rows = {row.get("name"): row for row in summary.get("features", [])}
row = rows.get(feature)
if row is None:
    print(f"[scenario] {feature}: missing in summary", file=sys.stderr)
    sys.exit(1)
active = bool(row.get("active"))
status = row.get("status")
expected_active = expect == "active"
if expected_active and not active:
    print(f"[scenario] {feature}: expected active, got status={status}", file=sys.stderr)
    sys.exit(2)
if not expected_active and active:
    print(f"[scenario] {feature}: expected inactive, got status={status}", file=sys.stderr)
    sys.exit(3)
PY
}

toggle_feature() {
  local feature="$1"
  local enabled="$2"
  local payload='{"enabled": false}'
  if [[ "$enabled" == "true" ]]; then
    payload='{"enabled": true}'
  fi
  curl -fsS -X POST \
    -H 'Content-Type: application/json' \
    -d "$payload" \
    "$BASE/api/logic/feature/${feature}" >>"$LOG"
}

say "Scenariusze App Logic (S3–S11)"
FEATURES=(
  "s3_follow_me_face"
  "s4_recon"
  "s5_voice"
  "s6_tracker_module"
  "s7_obstacle_module"
  "s8_mapping"
  "s9_navigation"
  "s10_ai_providers"
  "s11_dev_mode"
)
for feat in "${FEATURES[@]}"; do
  say "Start scenariusza $feat"
  toggle_feature "$feat" true
  sleep 1
  feature_check active "$feat"
  say "Stop scenariusza $feat"
  toggle_feature "$feat" false
  sleep 1
  feature_check inactive "$feat"
done

say "Logi bridge (150)"
run journalctl -u motion-executor.service -n 150 --no-pager | egrep -i 'rx_cmd.move|forward|stop|drop_old|auto_stop|START|STOP' || true

echo -e "\nSuite log: ${LOG}"
