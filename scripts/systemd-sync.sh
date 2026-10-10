#!/usr/bin/env bash
# Defaults to a read-only plan. Apply and boot consolidation are explicit.
set -euo pipefail
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${BASE_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 "${BASE_DIR}/scripts/systemd_reconcile.py" "$@"
