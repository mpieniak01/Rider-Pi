#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGDIR="$ROOT/tests/_logs"
mkdir -p "$LOGDIR"

API_URL="${API_URL:-http://127.0.0.1:8080}"
BR_URL="${BR_URL:-http://127.0.0.1:8081}"
CMD="${1:-start}"

if [[ "$CMD" == "stop" ]]; then
  if compgen -G "$LOGDIR/*.pid" > /dev/null; then
    while read -r p; do kill "$p" 2>/dev/null || true; done < <(cat "$LOGDIR"/*.pid)
    rm -f "$LOGDIR"/*.pid
    echo "Watchery zatrzymane."
  else
    echo "Brak PID-ów do zatrzymania."
  fi
  exit 0
fi

if command -v tmux >/dev/null 2>&1; then
  SESSION="rider-watch"
  if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux new-session -d -s "$SESSION" -n "logs"
    tmux send-keys -t "$SESSION":0.0 "journalctl -fu rider-motion-bridge.service" C-m
    tmux split-window -h -t "$SESSION":0.0
    tmux send-keys -t "$SESSION":0.1 "journalctl -fu rider-web-bridge.service" C-m
    tmux split-window -v -t "$SESSION":0.0
    tmux send-keys -t "$SESSION":0.2 "journalctl -fu rider-api.service" C-m
    tmux split-window -v -t "$SESSION":0.1
    tmux send-keys -t "$SESSION":0.3 "watch -n 2 'ss -ltnp | grep -E \":(8080|8081|5555|5556)\\s\" || true'" C-m
    tmux new-window -t "$SESSION" -n "events"
    tmux send-keys -t "$SESSION":1.0 "printf 'SSE from ${API_URL}/events\n'; curl -N -s ${API_URL}/events | sed -u -n 's/^data: //p'" C-m
  fi
  exec tmux attach -t "$SESSION"
fi

echo "tmux nie znaleziony → fallback do logów w $LOGDIR i tail -F"
stdbuf -oL journalctl -fu rider-motion-bridge.service > "$LOGDIR/motion.log" 2>&1 & echo $! > "$LOGDIR/motion.pid"
stdbuf -oL journalctl -fu rider-web-bridge.service    > "$LOGDIR/web.log"    2>&1 & echo $! > "$LOGDIR/web.pid"
stdbuf -oL journalctl -fu rider-api.service           > "$LOGDIR/api.log"    2>&1 & echo $! > "$LOGDIR/api.pid"
( while true; do ss -ltnp | grep -E ':(8080|8081|5555|5556)\s' || true; sleep 2; done ) > "$LOGDIR/ports.log" 2>&1 & echo $! > "$LOGDIR/ports.pid"
( printf "SSE from %s/events\n" "$API_URL"; curl -N -s "$API_URL/events" | sed -u -n 's/^data: //p' ) > "$LOGDIR/events.log" 2>&1 & echo $! > "$LOGDIR/events.pid"

echo -e "\nPodgląd (Ctrl-C aby wyjść). Zatrzymanie watcherów: bash tests/watch.sh stop"
exec tail -F "$LOGDIR"/{motion,web,api,ports,events}.log
