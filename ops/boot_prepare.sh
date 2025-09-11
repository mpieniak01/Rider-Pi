#!/usr/bin/env bash
# Rider-Pi — boot prepare: vendor cleanup + splash + LCD off
set -euo pipefail

# Parametry z unitu (z Environment=...), z sensownymi fallbackami:
SPLASH_SECONDS="${SPLASH_SECONDS:-5}"
SPLASH_ROTATE="${SPLASH_ROTATE:-270}"
SPLASH_CLEAR="${SPLASH_CLEAR:-1}"
BOOT_VENDOR_GRACE="${BOOT_VENDOR_GRACE:-5}"
LCD_BL_GPIO="${LCD_BL_GPIO:-13}"
LCD_OFF_CMD="${LCD_OFF_CMD:-/usr/bin/python3 /home/pi/robot/ops/lcdctl.py off}"

ROBOT_ROOT="${ROBOT_ROOT:-/home/pi/robot}"
MARKER_DIR="/run/rider"
MARKER_FILE="${MARKER_DIR}/boot-prepared"

log() { echo "[boot-prepare] $*"; }

# 1) Marker /run/rider/boot-prepared — jeśli istnieje, kończymy (chociaż ConditionPathExists powinien to odciąć).
mkdir -p "${MARKER_DIR}"
if [[ -f "${MARKER_FILE}" ]]; then
  log "marker already present, nothing to do."
  exit 0
fi

# 2) Poczekaj chwilę, aż system „dojdzie do siebie” i (ew.) wstanie vendor GUI.
log "grace for vendor processes: ${BOOT_VENDOR_GRACE}s"
sleep "${BOOT_VENDOR_GRACE}"

# 3) Ubicie znanych procesów vendora (XGO / python mainy, menedżery ekranowe, lightdm itp.)
#    Komendy są „best effort” (|| true).
log "killing known vendor/display processes (best-effort)"
pkill -f "/usr/bin/python3 .*xgo.*"      >/dev/null 2>&1 || true
pkill -f "/usr/bin/python3 .*main\.py"   >/dev/null 2>&1 || true
pkill -f "xgo.*screen"                   >/dev/null 2>&1 || true
pkill -f "lightdm"                       >/dev/null 2>&1 || true
pkill -f "display-manager"               >/dev/null 2>&1 || true

# 4) Splash z informacją o urządzeniu (prefer backend xgo; fallbacki ogólne).
SPLASH="${ROBOT_ROOT}/ops/splash_device_info.sh"
if [[ -x "${SPLASH}" ]]; then
  log "showing splash rotate=${SPLASH_ROTATE} seconds=${SPLASH_SECONDS} clear=${SPLASH_CLEAR}"
  env SPLASH_ROTATE="${SPLASH_ROTATE}" SPLASH_SECONDS="${SPLASH_SECONDS}" SPLASH_CLEAR="${SPLASH_CLEAR}" \
    "${SPLASH}" || log "splash failed (continuing)"
else
  log "splash script not executable or missing: ${SPLASH}"
fi

# 5) Wyłączenie podświetlenia przez GPIO (jeśli dostępne).
if command -v raspi-gpio >/dev/null 2>&1; then
  log "turning LCD backlight off via raspi-gpio GPIO${LCD_BL_GPIO}"
  raspi-gpio set "${LCD_BL_GPIO}" op dl || true
fi

# 6) Próba pełnego uśpienia panelu (komenda skryptowa; ignorujemy błąd).
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

