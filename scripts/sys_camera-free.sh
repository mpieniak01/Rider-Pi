#!/usr/bin/env bash
# Explicit V4L2 recovery uses the canonical resource guard.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
export PYTHONPATH="${BASE_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 "${SCRIPT_DIR}/camera_recovery.py" "$@"
