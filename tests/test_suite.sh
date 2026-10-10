#!/usr/bin/env bash
# Read-only observations. No service start, arming, flag clearing or motion.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${PYTHON:-python3}" "$REPO_ROOT/scripts/diag_motion-status.py" "${1:-http://127.0.0.1:8080}"
