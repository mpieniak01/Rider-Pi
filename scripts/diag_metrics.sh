#!/usr/bin/env bash
set -euo pipefail
WIN="${1:-60 seconds ago}"
while true; do
  since="$WIN"
  web_moves=$(journalctl -u rider-web-bridge.service --since "$since" -o cat | grep -c '\[web\].*/api/move')
  web_stops=$(journalctl -u rider-web-bridge.service --since "$since" -o cat | grep -c '\[web\].*/api/stop')
  rx=$(journalctl -u rider-motion-bridge.service --since "$since" -o cat | grep -c 'rx_cmd.move')
  fwd=$(journalctl -u rider-motion-bridge.service --since "$since" -o cat | grep -c ' forward[",]')   # event forward
  bwd=$(journalctl -u rider-motion-bridge.service --since "$since" -o cat | grep -c ' backward[",]')
  tl=$(journalctl -u rider-motion-bridge.service --since "$since" -o cat | grep -c ' turn_left[",]')
  tr=$(journalctl -u rider-motion-bridge.service --since "$since" -o cat | grep -c ' turn_right[",]')
  left=$(journalctl -u rider-motion-bridge.service --since "$since" -o cat | grep -c ' left[",]')
  right=$(journalctl -u rider-motion-bridge.service --since "$since" -o cat | grep -c ' right[",]')
  skip=$(journalctl -u rider-motion-bridge.service --since "$since" -o cat | grep -c 'skip_cmd.move')
  drop=$(journalctl -u rider-motion-bridge.service --since "$since" -o cat | grep -c 'reason": "drop_old"')
  gap=$(journalctl -u rider-motion-bridge.service --since "$since" -o cat | grep -c 'reason": "min_gap"')
  autos=$(journalctl -u rider-motion-bridge.service --since "$since" -o cat | grep -c 'auto_stop')
  acts=$((fwd + bwd + tl + tr + left + right))
  pct=0
  if [ "$rx" -gt 0 ]; then pct=$(( 100 * acts / rx )); fi
  echo "=== Window: since $since ==="
  printf "WEB  : moves=%d stops=%d\n" "$web_moves" "$web_stops"
  printf "BRG  : rx_cmd.move=%d  actions=%d (fwd=%d bwd=%d tl=%d tr=%d left=%d right=%d)\n" "$rx" "$acts" "$fwd" "$bwd" "$tl" "$tr" "$left" "$right"
  printf "SKIP : total=%d  drop_old=%d  min_gap=%d\n" "$skip" "$drop" "$gap"
  printf "AUTO : auto_stop=%d\n" "$autos"
  printf "OK%%  : %d%% (actions/rx)\n" "$pct"
  echo
  sleep 2
done
