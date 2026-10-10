#!/usr/bin/env bash
# Read-only admission check. It never kills owners or restores another task.
set -euo pipefail
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${BASE_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 "${BASE_DIR}/scripts/vision-resource-guard.py" "$@"
