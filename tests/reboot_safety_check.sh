#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ok(){ echo -e "[OK]  $*"; }
warn(){ echo -e "[! ] $*"; }
die(){ echo -e "[ERR] $*"; exit 1; }

wait_health() {
  local url="$1" tries="${2:-20}"
  for i in $(seq 1 "$tries"); do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}

echo "== Rider-Pi PRE-FLIGHT @ $(date) =="
echo "HEAD: $(git rev-parse --short HEAD 2>/dev/null || echo '?')"

NEEDED=(rider-broker.service rider-motion-bridge.service rider-web-bridge.service rider-api.service)
echo "== is-enabled =="
for s in "${NEEDED[@]}"; do
  st=$(systemctl is-enabled "$s" 2>/dev/null || echo "disabled")
  printf "  %-28s : %s\n" "$s" "$st"
  [[ "$st" == "enabled" ]] || warn "$s nie ma autostartu (sudo systemctl enable $s)"
done

echo "== systemd-analyze verify (repo/systemd/*.service) =="
systemd-analyze verify "$ROOT/systemd"/rider-{broker,motion-bridge,web-bridge,api}.service || die "verify failed"

echo "== daemon-reload & restart usług (bez rebootu) =="
sudo systemctl daemon-reload
sudo systemctl restart rider-broker.service
sleep 0.5
sudo systemctl restart rider-motion-bridge.service
sleep 0.5
sudo systemctl restart rider-web-bridge.service
sleep 0.5
sudo systemctl restart rider-api.service

echo "== czekam na healthz (do 20s) =="
wait_health "http://127.0.0.1:8081/healthz" 20 || die "8081/healthz FAIL"
wait_health "http://127.0.0.1:8080/healthz" 20 || die "8080/healthz FAIL"

echo "== smoke move =="
curl -fsS "http://127.0.0.1:8080/api/move?dir=forward&v=0.12&t=0.12" >/dev/null || die "move fail"
sleep 0.2
curl -fsS "http://127.0.0.1:8080/api/stop" >/dev/null || warn "stop warn"

ok "Preflight wygląda dobrze."
echo
read -rp "Zrobić reboot teraz? [t/N] " ans
case "${ans,,}" in
  t|y) echo "Reboot..."; sudo reboot ;;
  *)   echo "Pomiń reboot. (Możesz uruchomić później: sudo reboot)";;
esac
