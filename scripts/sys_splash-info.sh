#!/usr/bin/env bash
# Rider-Pi — unified splash wrapper (xgo/pygame/auto) with Makefile fallback
set -euo pipefail

ROOT="${ROBOT_ROOT:-/home/pi/robot}"
ROTATE="${SPLASH_ROTATE:-270}"
SECONDS="${SPLASH_SECONDS:-10}"
CLEAR="${SPLASH_CLEAR:-0}"
USE="${SPLASH_USE:-auto}"

PY="${PYTHON:-/usr/bin/python3}"
PY_IMPL="${ROOT}/scripts/sys_splash-info.py"
LEGACY_PY="${ROOT}/scripts/splash_device_info.py"   # dawna nazwa (jeśli istnieje)

log(){ echo "[splash-wrapper] $*"; }

if [[ -f "${PY_IMPL}" ]]; then
  log "python splash -> ${PY_IMPL} (rotate=${ROTATE}, seconds=${SECONDS}, clear=${CLEAR}, use=${USE})"
  env SPLASH_ROTATE="${ROTATE}" SPLASH_SECONDS="${SECONDS}" SPLASH_CLEAR="${CLEAR}" SPLASH_USE="${USE}" \
    "${PY}" "${PY_IMPL}"
elif [[ -f "${LEGACY_PY}" ]]; then
  log "python legacy splash -> ${LEGACY_PY} (rotate=${ROTATE}, seconds=${SECONDS}, clear=${CLEAR}, use=${USE})"
  env SPLASH_ROTATE="${ROTATE}" SPLASH_SECONDS="${SECONDS}" SPLASH_CLEAR="${CLEAR}" SPLASH_USE="${USE}" \
    "${PY}" "${LEGACY_PY}"
else
  log "no python splash found, fallback to Makefile testcard (seconds=${SECONDS})"
  # Fallback: kolorowa plansza na LCD
  FACE_LCD_ROTATE="${ROTATE}" FACE_LCD_SPI_HZ="${FACE_LCD_SPI_HZ:-32000000}" \
    sudo -E make -C "${ROOT}" face-testcard || true
  sleep "${SECONDS}"
  if [[ "${CLEAR}" == "1" ]]; then
    make -C "${ROOT}" lcd-black || true
  fi
fi
