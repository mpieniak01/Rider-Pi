#!/usr/bin/env bash
set -euo pipefail
echo "[takeover-pre] ubijam potencjalne procesy producenta…"

# procesy pythona, które mogą używać naszego LCD/kamery
PATS=(
  'yolostream.py'
  'camera_dogzilla.py'
  'xgolib'
  'xgoedu'
  'LCD_2inch'
  'mediapipe'
  'vendor_splash.py'
)
for p in "${PATS[@]}"; do pkill -9 -f "$p" 2>/dev/null || true; done

# serwerowe porty w przykładach vendora
sudo fuser -k 6500/tcp 7700/tcp 2>/dev/null || true

# urządzenia SPI LCD (zwolnij wszystko co je trzyma)
for d in /dev/spidev0.0 /dev/spidev0.1; do
  [ -e "$d" ] && sudo fuser -kv "$d" 2>/dev/null || true
done

# zatrzymaj potencjalne usługi, o ile są
sudo systemctl stop yolostream.service 2>/dev/null || true
sudo systemctl stop xgo* 2>/dev/null || true

# wyczyść nasz lock
rm -f /tmp/rider_spi_lcd.lock

# podświetlenie ON
sudo raspi-gpio set 13 op dh 2>/dev/null || true
echo "[takeover-pre] gotowe"