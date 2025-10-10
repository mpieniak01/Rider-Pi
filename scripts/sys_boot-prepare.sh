#!/usr/bin/env bash
# Rider-Pi — boot prepare: vendor cleanup + splash + LCD off
set -euo pipefail

# Parametry z unitu (z Environment=...), z sensownymi fallbackami:
SPLASH_SECONDS="${SPLASH_SECONDS:-5}"
SPLASH_ROTATE="${SPLASH_ROTATE:-270}"
SPLASH_CLEAR="${SPLASH_CLEAR:-1}"
SPLASH_USE="${SPLASH_USE:-}"                 # opcjonalnie: xgo|pygame|auto
BOOT_VENDOR_GRACE="${BOOT_VENDOR_GRACE:-5}"
LCD_BL_GPIO="${LCD_BL_GPIO:-0}"              # domyślnie BCM0
LCD_OFF_CMD="${LCD_OFF_CMD:-/usr/bin/python3 /home/pi/robot/scripts/sys_lcd-control.py off}"
KEEP_BL_ON="${KEEP_BL_ON:-0}"                # 1 = zostaw BL włączone
NO_KILL_DISPLAY="${NO_KILL_DISPLAY:-0}"      # 1 = NIE ubijaj lightdm/display-manager

ROBOT_ROOT="${ROBOT_ROOT:-/home/pi/robot}"
MARKER_DIR="/run/rider"
MARKER_FILE="${MARKER_DIR}/boot-prepared"

log() { echo "[boot-prepare] $*"; }

# 1) Marker
mkdir -p "${MARKER_DIR}"
if [[ -f "${MARKER_FILE}" ]]; then
  log "marker already present, nothing to do."
  exit 0
fi

# 2) Krótki grace period dla usług vendora/GUI
log "grace for vendor processes: ${BOOT_VENDOR_GRACE}s"
sleep "${BOOT_VENDOR_GRACE}"

# 3) Best-effort ubicie potencjalnych procesów trzymających LCD (bez display-manager jeśli NO_KILL_DISPLAY=1)
log "killing known vendor/display processes (best-effort)"
pkill -f "/usr/bin/python3 .*xgo.*"      >/dev/null 2>&1 || true
pkill -f "/usr/bin/python3 .*main\.py"   >/dev/null 2>&1 || true
pkill -f "xgo.*screen"                   >/dev/null 2>&1 || true
if [[ "${NO_KILL_DISPLAY}" != "1" ]]; then
  pkill -f "lightdm"          >/dev/null 2>&1 || true
  pkill -f "display-manager"  >/dev/null 2>&1 || true
else
  log "NO_KILL_DISPLAY=1 -> skipping LightDM/display-manager kill"
fi

# 4) Splash
SPLASH_SH="${ROBOT_ROOT}/scripts/sys_splash-info.sh"
SPLASH_PY="${ROBOT_ROOT}/scripts/sys_splash-info.py"
if [[ -x "${SPLASH_SH}" ]]; then
  log "showing splash rotate=${SPLASH_ROTATE} seconds=${SPLASH_SECONDS} clear=${SPLASH_CLEAR} use=${SPLASH_USE:-auto}"
  env \
    SPLASH_ROTATE="${SPLASH_ROTATE}" \
    SPLASH_SECONDS="${SPLASH_SECONDS}" \
    SPLASH_CLEAR="${SPLASH_CLEAR}" \
    ${SPLASH_USE:+SPLASH_USE="${SPLASH_USE}"} \
    "${SPLASH_SH}" || log "splash (.sh) failed (continuing)"
elif [[ -f "${SPLASH_PY}" ]]; then
  log "showing splash (py) rotate=${SPLASH_ROTATE} seconds=${SPLASH_SECONDS} clear=${SPLASH_CLEAR} use=${SPLASH_USE:-auto}"
  env \
    SPLASH_ROTATE="${SPLASH_ROTATE}" \
    SPLASH_SECONDS="${SPLASH_SECONDS}" \
    SPLASH_CLEAR="${SPLASH_CLEAR}" \
    ${SPLASH_USE:+SPLASH_USE="${SPLASH_USE}"} \
    /usr/bin/python3 "${SPLASH_PY}" || log "splash (.py) failed (continuing)"
else
  log "splash script not found: ${SPLASH_SH} / ${SPLASH_PY}"
fi

# 5) Sterowanie podświetleniem
if command -v raspi-gpio >/dev/null 2>&1; then
  if [[ "${KEEP_BL_ON}" = "1" ]]; then
    log "leaving LCD backlight ON (debug); forcing GPIO${LCD_BL_GPIO}=HIGH"
    raspi-gpio set "${LCD_BL_GPIO}" op dh || true
  else
    log "turning LCD backlight off via raspi-gpio GPIO${LCD_BL_GPIO}"
    raspi-gpio set "${LCD_BL_GPIO}" op dl || true
  fi
fi

# 6) Panel OFF (jeśli chcesz wyłączyć sygnały do LCD)
if [[ -n "${LCD_OFF_CMD}" ]]; then
  log "turning LCD panel off: ${LCD_OFF_CMD}"
  set +e
  bash -lc "${LCD_OFF_CMD}"
  set -e
fi

# 7) Zapis markera
date -Is | tee "${MARKER_FILE}" >/dev/null
log "done; marker written to ${MARKER_FILE}"
exit 0
