#!/usr/bin/env bash
# camera_takeover_kill.sh — free camera/SPI and light up LCD backlight
# Safe hard-kill of preview pipelines + free busy devices.
# BL pin: GPIO 13 (active-high)

set -euo pipefail

echo "=== [takeover-kill] begin ==="

# 1) Podświetlenie LCD (BL ON), jeśli narzędzie dostępne
if command -v raspi-gpio >/dev/null 2>&1; then
  raspi-gpio set 13 op dh || true
fi

# 2) (opcjonalnie) Wyłącz vendor splash — tylko jeśli plik istnieje
if [ -f "scripts/vendor_splash.py" ]; then
  python3 -u scripts/vendor_splash.py --off || true
fi

# 3) Zabicie naszych pipeline’ów preview
pkill -f 'apps/camera/preview_lcd_takeover.py' || true
pkill -f 'apps/camera/preview_lcd_ssd.py' || true
pkill -f 'apps/camera/preview_lcd_hybrid.py' || true
pkill -f 'preview_lcd_takeover.py' || true
pkill -f 'preview_lcd_ssd.py' || true
pkill -f 'preview_lcd_hybrid.py' || true

# 4) Zabicie resztek libcamera/rpicam/streamerów, jeśli wiszą
pkill -f 'libcamera' || true
pkill -f 'rpicam-' || true
pkill -f 'raspivid' || true
pkill -f 'raspistill' || true
pkill -f 'v4l2' || true
pkill -f 'mjpg_streamer' || true

# 5) Force-close uchwytów do urządzeń: SPI i kamera
for dev in /dev/spidev0.0 /dev/spidev0.1 /dev/video0; do
  if [ -e "$dev" ]; then
    sudo fuser -k "$dev" 2>/dev/null || true
  fi
done

# (opcjonalnie) zwolnij uchwyty do GPIO chipów — nie szkodzi, gdy brak
sudo fuser -k /dev/gpiochip* 2>/dev/null || true

echo "=== [takeover-kill] done ==="
