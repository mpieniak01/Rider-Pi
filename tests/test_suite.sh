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

say "Logi bridge (150)"
run journalctl -u rider-motion-bridge -n 150 --no-pager | egrep -i 'rx_cmd.move|forward|stop|drop_old|auto_stop|START|STOP' || true

echo -e "\nSuite log: ${LOG}"
