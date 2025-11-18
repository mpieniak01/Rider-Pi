#!/usr/bin/env bash
#
# scripts/vision-resource-guard.sh
#
# Ensure vision offload owns the camera and related resources when starting,
# and restore preview services once offload stops.

set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VISION_PREVIEW_SERVICES=(
  rider-cam-preview.service
  rider-edge-preview.service
  rider-ssd-preview.service
)

claim_resources() {
  echo "[vision-resource] claiming camera resources" >&2
  for svc in "${VISION_PREVIEW_SERVICES[@]}"; do
    if systemctl list-unit-files "$svc" >/dev/null 2>&1; then
      if systemctl --quiet is-active "$svc"; then
        echo "[vision-resource] stopping ${svc}" >&2
        systemctl stop "$svc"
      fi
    fi
  done
}

release_resources() {
  echo "[vision-resource] releasing camera resources" >&2
  for svc in "${VISION_PREVIEW_SERVICES[@]}"; do
    if systemctl list-unit-files "$svc" >/dev/null 2>&1; then
      echo "[vision-resource] starting ${svc}" >&2
      systemctl start "$svc" || true
    fi
  done
}

usage() {
  echo "Usage: $0 {claim|release}" >&2
  exit 2
}

if [[ $# -ne 1 ]]; then
  usage
fi

case "$1" in
  claim)
    claim_resources
    ;;
  release)
    release_resources
    ;;
  *)
    usage
    ;;
esac
