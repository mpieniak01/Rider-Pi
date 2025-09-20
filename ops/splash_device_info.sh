#!/usr/bin/env bash
# disable showing when early boot wants to skip
[ "${EARLY_SPLASH:-0}" = "1" ] && exit 0
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$DIR/splash_device_info.py"

