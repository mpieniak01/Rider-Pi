##Rider-Pi v0.5.1 — stable motion chain##

###Highlights###
- Stabilny łańcuch ruchu: dashboard→API(:8080)→web-bridge(:8081)→BUS→motion-bridge→XGO
- API w trybie router-only (przejrzyste proxy do mostka)
- web-bridge na :8081 (brak kolizji z API)
- Bench-safe limity: SAFE_MAX_DURATION=0.12, MIN_CMD_GAP=0.01, DEADMAN_MS=400
- tests/: diag_snapshot, watch, cascade_forward (diagnostyka + kaskady)


###Smoke test###
- curl 127.0.0.1:8081/healthz && curl 127.0.0.1:8080/healthz
- curl "127.0.0.1:8080/api/move?dir=forward&v=0.15&t=0.12" ; curl "127.0.0.1:8080/api/stop"
- journalctl -u rider-motion-bridge.service -n 40 | egrep -i 'rx_cmd|forward|backward|stop'


## v0.4.8 — 2025-09-03

### Ops & boot
- `boot_prepare.sh` + `rider-boot-prepare.service`: bezpieczny start (kill vendor GUI), splash, `/run/rider`.
- `splash_device_info.{sh,py}` + `rider-splash.service`: ekran startowy z czytelnym OS/host/IP.
- `systemd`: `rider-minimal.target`, `rider-vision.service`, `rider-last-frame-sink.service`,
  drop-in `rider-ui-manager.service.d/`, update `rider-api.service`, `rider-menu.service`.
- Repo-first systemd: sync przez `ops/systemd_sync.sh`.

### Vision & camera
- `apps/camera/preview_lcd.py`: stabilizacja FPS, heartbeat, korekty prezentacji na LCD.
- `apps/vision/dispatcher.py`: progi obecności (on_consecutive/off_ttl/min_score), heartbeat, publikacje topiców.
- `services/last_frame_sink.py`: lekki sink ostatniej ramki (integracja z dashboardem).

### UI / Web
- `web/control.html`, `web/view.html`: poprawki layoutu, czytelność, szybsze odświeżanie.

### API / Services
- `services/status_api.py`: rozszerzone metryki i heartbeat (CPU/MEM/LOAD/DISK/TEMP, devices).

### Inne
- `ops/lcdctl.py`: ON/OFF panelu (SLP/DISP) i BL; ujednolicone sterowanie.
- `Makefile`: cele dev/test/ops; lepszy smoke path.

### Housekeeping
- `.gitignore`: `scripts/`, `data/`, `_diag/`, `web/*.tmp`, `__pycache__`, itp.
