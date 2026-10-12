#!/usr/bin/env bash
# Compatibility alias. Uses current ownership; never kills arbitrary processes.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${RIDER_PYTHON:-python3}" "$SCRIPT_DIR/resource_ctl.py" camera stop "$@"
