# Rider-Pi v0.5.3 — post-splash tylko raz, po IPv4

## Highlights
- **Post-splash** rysowany **raz**, dopiero gdy:
  - API `/healthz` działa,
  - dostępne jest **IPv4** (czeka do `SPLASH_WAIT_IP_S`, domyślnie 60 s).
- Brak pokazywania MAC/„—” — IP wykrywane przez `ip route get`/`hostname -I`.
- Jeden punkt wejścia: **Python** (`ops/splash_device_info.py`) – usunięte duplikaty `.sh`.
- **Log** diagnostyczny: `data/splash_trace.log` (ścieżka detekcji IP, backend, „render OK”).
- **Boot-splash** skrócony do **3 s** (mniej migania).

## Zmiany techniczne
- `systemd/rider-post-splash.service` → pojedynczy `ExecStart`:
  `SPLASH_WAIT_IP_S=60 /usr/bin/python3 ops/splash_device_info.py`
- `systemd/rider-boot-prepare.service` → `SPLASH_SECONDS=3`
- Usunięte: `ops/splash_device_info.sh`, `ops/net_wait_ip.sh` (zastąpione logiką w Pythonie).

## Upgrade (na urządzeniu)
1. `git pull && git checkout v0.5.3`
2. `sudo systemctl daemon-reload`
3. `sudo systemctl restart rider-boot-prepare.service rider-post-splash.service`

## Smoke test
- `journalctl -u rider-post-splash.service -n 50` → szukaj „render OK” i „IP via …”.
- `SPLASH_WAIT_IP_S=10 python3 ops/splash_device_info.py` (powinno pokazać IP i zapisać log).

