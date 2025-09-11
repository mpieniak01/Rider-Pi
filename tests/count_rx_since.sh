#!/usr/bin/env bash
set -euo pipefail
SINCE="${1:-2 minutes ago}"

echo "== Zdarzenia BRIDGE (rider-motion-bridge.service) od: ${SINCE} =="
journalctl -u rider-motion-bridge.service --since "${SINCE}" --no-pager \
  | awk 'BEGIN{rx=0;sk=0;as=0;st=0}
         /rx_cmd\.move/{rx++}
         /skip_cmd\.move/{sk++}
         /auto_stop/{as++}
         /\] stop$/{st++}
         END{printf "rx_cmd.move=%d, skip_cmd.move=%d, auto_stop=%d, stop=%d\n", rx, sk, as, st}'

echo "== Trafienia WEB (rider-web-bridge.service) od: ${SINCE} =="
journalctl -u rider-web-bridge.service --since "${SINCE}" --no-pager \
  | awk 'BEGIN{m=0;s=0}
         /GET \/api\/move|POST \/api\/move/{m++}
         /GET \/api\/stop|POST \/api\/stop/{s++}
         END{printf "/api/move=%d, /api/stop=%d\n", m, s}'
