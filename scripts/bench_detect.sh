#!/usr/bin/env bash
set -euo pipefail

DUR="${1:-25}"                 # czas pomiaru [s]
ROT="${PREVIEW_ROT:-270}"
SCORE="${SSD_SCORE:-0.6}"
W="${CAM_W:-640}"
H="${CAM_H:-480}"

avg_from_log() {
  local f="$1"
  # Wyciągnij same liczby „fps=…” i policz średnią
  if [ ! -s "$f" ]; then echo "0.00"; return; fi
  sed -n 's/.*fps=\([0-9.][0-9.]*\).*/\1/p' "$f" \
  | awk '{s+=$1; n++} END{if(n) printf "%.2f", s/n; else print "0.00"}'
}

cleanup() {
  pkill -f "apps/ui/face.py" || true
  pkill -f "apps/camera/preview_lcd_ssd.py" || true
  pkill -f "apps/camera/preview_lcd_takeover.py" || true
  sudo raspi-gpio set 13 op dh || true   # na koniec podświetlenie znów ON
}
trap cleanup EXIT

echo "== Rider-Pi bench (DUR=${DUR}s, ROT=${ROT}, SSD_SCORE=${SCORE}, CAM=${W}x${H}) =="

# twardy pre-kill vendorów i podświetlenie ON
bash scripts/camera_takeover_kill.sh || true
sudo raspi-gpio set 13 op dh || true

# --- SSD ---
echo "-- SSD run --"
: > /tmp/fps_ssd.log
( KEEP_LCD=1 BENCH_LOG=1 SKIP_V4L2=1 PREVIEW_ROT="${ROT}" SSD_SCORE="${SCORE}" CAM_W="${W}" CAM_H="${H}" \
  timeout "${DUR}"s python3 -u apps/camera/preview_lcd_ssd.py 2>&1 \
  | stdbuf -oL grep -F "[bench] fps=" | tee /tmp/fps_ssd.log ) || true
SSD_AVG="$(avg_from_log /tmp/fps_ssd.log)"
echo "SSD_avg_fps=${SSD_AVG}"

# ponownie włącz BL (gdyby skrypt go zgasił)
sudo raspi-gpio set 13 op dh || true
sleep 0.3

# --- HAAR ---
echo "-- HAAR run --"
: > /tmp/fps_haar.log
( KEEP_LCD=1 BENCH_LOG=1 SKIP_V4L2=1 PREVIEW_ROT="${ROT}" VISION_HUMAN=1 VISION_FACE_EVERY=5 \
  timeout "${DUR}"s python3 -u apps/camera/preview_lcd_takeover.py 2>&1 \
  | stdbuf -oL grep -F "[bench] fps=" | tee /tmp/fps_haar.log ) || true
HAAR_AVG="$(avg_from_log /tmp/fps_haar.log)"
echo "HAAR_avg_fps=${HAAR_AVG}"

echo "== RESULT ==  SSD:${SSD_AVG} fps   |   HAAR:${HAAR_AVG} fps"
