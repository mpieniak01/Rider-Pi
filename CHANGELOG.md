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
