#!/usr/bin/env bash
# Public camera goal; the API starts the capture/feed package atomically.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${RIDER_PYTHON:-python3}" "$SCRIPT_DIR/robot_ctl.py" start s2_camera_preview "$@"
