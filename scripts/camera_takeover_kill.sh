#!/usr/bin/env bash


set -euo pipefail

echo "[takeover-pre] ubijam potencjalne procesy producenta…"

PATS=(
  "python3 -m apps.ui.face"
  "python3 -m apps.camera"
  "apps/camera/preview_lcd_takeover.py"
  "xgo"
  "libcamera-"
  "rpicam-"
  "picamera2"
  "libcamera-hello"
)

for pat in "${PATS[@]}"; do pkill -TERM -f "$pat" 2>/dev/null || true; done
sleep 0.4
for pat in "${PATS[@]}"; do pkill -KILL -f "$pat" 2>/dev/null || true; done

# uwolnij wezelki /dev
for n in /dev/media* /dev/video*; do fuser -k "$n" 2>/dev/null || true; done

# podnies podswietlenie i rozbudz panel (gdyby byl uspiony)
sudo -n python3 scripts/lcdctl.py on >/dev/null 2>&1 || sudo python3 scripts/lcdctl.py on

echo "[takeover-pre] gotowe"