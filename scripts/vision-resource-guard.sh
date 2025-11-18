#!/usr/bin/env bash
#
# scripts/vision-resource-guard.sh
#
# Ensure vision offload owns the camera and related resources when starting,
# and restore preview services once offload stops.

set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VISION_PREVIEW_SERVICES=(
)

claim_resources() {
  echo "[vision-resource] claiming camera resources" >&2
  for svc in "${VISION_PREVIEW_SERVICES[@]}"; do
    :
  done
}

release_resources() {
  echo "[vision-resource] releasing camera resources" >&2
  for svc in "${VISION_PREVIEW_SERVICES[@]}"; do
    :
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
