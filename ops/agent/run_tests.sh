#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"

# venv
. "$ROOT/.venv/bin/activate"

# Bezpieczne ENV — bez HW
export RIDER_APPS_PATH="${RIDER_APPS_PATH:-_apps:apps}"
export FACE_LCD_ROTATE="${FACE_LCD_ROTATE:-0}"
export FACE_LCD_SPI_HZ="${FACE_LCD_SPI_HZ:-32000000}"
export FACE_LCD_FIT="${FACE_LCD_FIT:-fill}"
export FACE_SINK="${FACE_SINK:-png}"
export RIDER_NO_HW="${RIDER_NO_HW:-1}"

# Walidacja składni (bez HW)
python -m compileall -q services/api_core/*.py services/api_server.py apps/ui/face/*.py || true

# Minimalny zestaw testów
pytest -q tests/test_face_anim_api.py --timeout=10 --maxfail=1
