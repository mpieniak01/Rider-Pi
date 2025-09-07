#!/usr/bin/env bash
set -Eeo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTDIR="$ROOT/tests/_artifacts/diag"
mkdir -p "$OUTDIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$OUTDIR/diag_$STAMP.txt"

INTERACTIVE=0
[[ -t 1 && -z "${TMUX:-}" ]] && INTERACTIVE=1

err(){ code=$?; echo -e "\n[ERROR] Kod $code w linii ${BASH_LINENO[0]}." | tee -a "$OUT"; }
trap err ERR
finish(){
  echo -e "\nOK. Zapisano: $OUT"
  if [[ $INTERACTIVE -eq 1 ]]; then
    echo -e "\n--- Podgląd ostatnich 60 linii ---"
    tail -n 60 "$OUT" || true
    echo -ne "\nEnter, aby zamknąć… "; read -r _
  fi
}
trap finish EXIT
sec(){ echo -e "\n===== $* =====" | tee -a "$OUT"; }

{
  echo "Rider-Pi snapshot @ $(date)"
  echo "Host: $(uname -a)"
  echo "Uptime: $(uptime)"
} | tee "$OUT"

SERVICES=(rider-broker.service rider-web-bridge.service rider-motion-bridge.service rider-api.service)

sec "systemd: is-active / is-enabled"
for s in "${SERVICES[@]}"; do
  printf "%-28s active=%-8s enabled=%s\n" "$s" "$(systemctl is-active "$s" || true)" "$(systemctl is-enabled "$s" 2>/dev/null || echo 'n/a')" | tee -a "$OUT"
done

sec "systemd: status (skróty)"
for s in "${SERVICES[@]}"; do
  echo -e "\n--- $s ---" | tee -a "$OUT"
  systemctl --no-pager -l status "$s" | sed -n '1,25p' | tee -a "$OUT" || true
done

sec "systemd: Environment"
for s in "${SERVICES[@]}"; do
  echo -e "\n--- $s ---" | tee -a "$OUT"
  systemctl show "$s" -p Environment | tee -a "$OUT" || true
done

# Jeśli 'systemctl cat' u Ciebie nie działa, zakomentuj poniższą sekcję.
sec "systemd: unit pliki (cat)"
for s in "${SERVICES[@]}"; do
  echo -e "\n--- $s ---" | tee -a "$OUT"
  systemctl cat "$s" | tee -a "$OUT" || true
done

sec "Ports (ss) listening 8080/8081/5555/5556"
(ss -ltnp || true) | (grep -E ':(8080|8081|5555|5556)\s' || true) | tee -a "$OUT"

sec "Ports (lsof)"
( command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP -sTCP:LISTEN || true ) | (grep -E ':(8080|8081|5555|5556)\b' || true) | tee -a "$OUT"

sec "Health checks"
for url in \
  "http://127.0.0.1:8081/healthz" \
  "http://127.0.0.1:8080/healthz" \
  "http://127.0.0.1:8080/state" \
  "http://127.0.0.1:8080/sysinfo" \
  "http://127.0.0.1:8080/api/status" \
; do
  echo -n "$url -> " | tee -a "$OUT"
  (curl -fsS --max-time 2 "$url" | tr -d '\n' | cut -c1-200 || echo "ERROR") | tee -a "$OUT"
  echo | tee -a "$OUT"
done

sec "SSE /events (nagłówki)"
curl -fsSI --max-time 2 "http://127.0.0.1:8080/events" | tee -a "$OUT" || true
