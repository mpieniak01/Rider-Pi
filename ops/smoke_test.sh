#!/usr/bin/env bash
# ops/smoke_test.sh — krótki test podglądu kamery + sprzątanie
# PASS/FAIL z exit code i jednoznacznym logiem

set -euo pipefail

DUR="${1:-3}"        # czas każdej próby (s)
ROT="${PREVIEW_ROT:-270}"
KEEP="${KEEP_LCD:-0}"

pass() { echo "[SMOKE PASS] $*"; exit 0; }
fail() { echo "[SMOKE FAIL] $*" >&2; exit 1; }

cleanup() {
  ./ops/camera_takeover_kill.sh || true
  if [ "${KEEP}" != "1" ] && command -v raspi-gpio >/dev/null 2>&1; then
    raspi-gpio set 13 op dl || true     # BL OFF
  fi
  # sanity: nie powinno nic wisieć
  pgrep -af 'preview_lcd|libcamera|mjpg|rpicam|raspivid|raspistill' >/dev/null && \
    echo "[SMOKE WARN] some camera processes still running" >&2 || true
}
trap cleanup EXIT

export SKIP_V4L2=1 PREVIEW_ROT="${ROT}"

run_with_timeout() {
  local name="$1"; shift
  local status=0
  timeout "${DUR}"s "$@" || status=$?
  # 124 = timeout (OK, bo celowo przerywamy po DUR s), 0 = też OK (dobrowolne zakończenie)
  if [ "$status" -ne 124 ] && [ "$status" -ne 0 ]; then
    fail "$name exited with code $status"
  fi
}

# 1) HAAR
run_with_timeout "takeover (HAAR)" python3 -u apps/camera/preview_lcd_takeover.py
./ops/camera_takeover_kill.sh || true

# 2) SSD
export SSD_EVERY="${SSD_EVERY:-2}" SSD_CLASSES="${SSD_CLASSES:-person}" SSD_SCORE="${SSD_SCORE:-0.55}"
run_with_timeout "SSD" python3 -u apps/camera/preview_lcd_ssd.py
./ops/camera_takeover_kill.sh || true

# 3) HYBRID
export HYBRID_HAAR="${HYBRID_HAAR:-1}"
run_with_timeout "HYBRID" python3 -u apps/camera/preview_lcd_hybrid.py

pass "camera preview pipelines ran ~${DUR}s each; cleanup OK"

