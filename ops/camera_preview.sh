#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

: "${SKIP_V4L2:=1}"
: "${PREVIEW_ROT:=270}"
: "${VISION_HUMAN:=1}"
: "${VISION_FACE_EVERY:=5}"
: "${PREVIEW_WARMUP:=12}"

# takeover / killer
bash ops/camera_takeover_kill.sh

CMD=(sudo -E python3 -m apps.camera --rot "$PREVIEW_ROT" --warmup "$PREVIEW_WARMUP")
[[ "$SKIP_V4L2" == "1" ]] && CMD+=(--skip-v4l2)
[[ "$VISION_HUMAN" == "1" ]] && CMD+=(--human 1 --every "$VISION_FACE_EVERY")

exec "${CMD[@]}"
