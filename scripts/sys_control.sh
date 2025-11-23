#!/usr/bin/env bash
# robot/scripts/sys_control.sh
set -euo pipefail


# ===== Whitelist (pełne nazwy unitów) =====
ALLOW_UNITS=(
  rider-api.service
  rider-broker.service
  camera-capture@raw.service
  camera-capture@edge.service
  camera-capture@ssd.service
  rider-google-bridge.service
  rider-mapper.service
  motion-executor.service
  sensor-reader.service
  rider-obstacle.service
  rider-odometry.service
  rider-tracker.service
  rider-tracking-controller.service
  rider-navigator.service
  rider-voice.service
  rider-voice-web.service
  rider-vision.service
  rider-vision-offload.service
  rider-web-bridge.service
  frame-distributor.service
  rider-core.target
  rider-followme.target
  rider-recon.target
  rider-voice.target
  rider-mapbuild.target
  rider-navigate.target
)


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
UNIT_SRC_DIR="${BASE_DIR}/systemd"
VISION_RESOURCE_SCRIPT="${BASE_DIR}/scripts/vision-resource-guard.sh"
VISION_RESOURCE_STATE="idle"

USER_NAME="pi"
USER_UID="$(id -u "$USER_NAME" 2>/dev/null || echo 1000)"
RUNTIME_DIR="/run/user/${USER_UID}"

is_allowed() {
  local u="$1"
  for x in "${ALLOW_UNITS[@]}"; do [[ "$u" == "$x" ]] && return 0; done
  return 1
}
is_action() { case "$1" in start|stop|restart|enable|disable) return 0;; esac; return 1; }

vision_claim_resources() {
  if [[ "$VISION_RESOURCE_STATE" == "claimed" ]]; then
    return
  fi
  if [[ -x "$VISION_RESOURCE_SCRIPT" ]]; then
    "$VISION_RESOURCE_SCRIPT" claim || true
    VISION_RESOURCE_STATE="claimed"
  fi
}

vision_release_resources() {
  if [[ "$VISION_RESOURCE_STATE" != "claimed" ]]; then
    return
  fi
  if [[ -x "$VISION_RESOURCE_SCRIPT" ]]; then
    "$VISION_RESOURCE_SCRIPT" release || true
    VISION_RESOURCE_STATE="idle"
  fi
}

maybe_release_resources() {
  if [[ "$UNIT" == "rider-vision-offload.service" && "$ACTION" == "stop" ]]; then
    vision_release_resources
  fi
}

# --- parse args: akceptuj obie kolejności ---
A="${1:-}"; B="${2:-}"
[[ -z "$A" || -z "$B" ]] && { echo "usage: $0 <unit> <start|stop|restart|enable|disable> (order free)" >&2; exit 2; }

if is_action "$A"; then ACTION="$A"; UNIT="$B"
elif is_action "$B"; then UNIT="$A"; ACTION="$B"
else echo "bad args: need unit + action (start/stop/restart/enable/disable)" >&2; exit 2
fi

if [[ "$UNIT" == "rider-vision-offload.service" && "$ACTION" == "start" ]]; then
  vision_claim_resources
fi

# --- whitelist ---
if ! is_allowed "$UNIT"; then
  echo "DENY: unit '$UNIT' not in whitelist" >&2
  exit 3
fi

# --- helpers: spróbuj SYSTEM, potem USER; zbierz diagnostykę ---
SYSTEMCTL_UNIT="$UNIT"
if [[ "$ACTION" == "enable" ]]; then
  UNIT_SRC_PATH="${UNIT_SRC_DIR}/${UNIT}"
  if [[ -f "$UNIT_SRC_PATH" && ! -e "/etc/systemd/system/${UNIT}" ]]; then
    SYSTEMCTL_UNIT="$UNIT_SRC_PATH"
    systemctl daemon-reload >/dev/null 2>&1 || true
  fi
fi

run_system() {
  systemctl --no-pager "$ACTION" "$SYSTEMCTL_UNIT" 2>&1
  return $?
}
run_user() {
  sudo -u "$USER_NAME" XDG_RUNTIME_DIR="$RUNTIME_DIR" systemctl --user --no-pager "$ACTION" "$UNIT" 2>&1
  return $?
}

# 1) spróbuj jako SYSTEM
OUT_SYS="$(run_system)"; RC_SYS=$?
if [[ $RC_SYS -eq 0 ]]; then
  [[ -n "$OUT_SYS" ]] && echo "$OUT_SYS"
  maybe_release_resources
  exit 0
fi

# 2) spróbuj jako USER
OUT_USER="$(run_user)"; RC_USER=$?
if [[ $RC_USER -eq 0 ]]; then
  [[ -n "$OUT_USER" ]] && echo "$OUT_USER"
  maybe_release_resources
  exit 0
fi

# 3) oba nie wyszły — wybierz lepszy komunikat
# preferuj komunikaty "not found"/"could not be found" jeśli wystąpiły
if echo "$OUT_SYS"$'\n'"$OUT_USER" | grep -qiE 'not found|could not be found'; then
  echo "$OUT_SYS"$'\n'"$OUT_USER" | grep -iE 'not found|could not be found' | head -n1 >&2
else
  # w innym wypadku pokaż krótszy, ale treściwy stderr
  if [[ ${#OUT_SYS} -le ${#OUT_USER} ]]; then
    echo "$OUT_SYS" | tail -n2 >&2
  else
    echo "$OUT_USER" | tail -n2 >&2
  fi
fi
exit 5
