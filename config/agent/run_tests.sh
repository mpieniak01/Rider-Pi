#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"

# Reuse the primary checkout's existing WSL venv, also from a worktree.
COMMON_GIT="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)"
TEST_PY="${RIDER_PI_TEST_PY:-$(dirname "$COMMON_GIT")/.venv/bin/python}"
if [[ ! -x "$TEST_PY" ]]; then
  echo "Missing Rider-Pi WSL venv; see docs/ENVIRONMENT_POLICY.md" >&2
  exit 1
fi

# Bezpieczne ENV — bez HW
export FACE_LCD_ROTATE="${FACE_LCD_ROTATE:-0}"
export FACE_LCD_SPI_HZ="${FACE_LCD_SPI_HZ:-32000000}"
export FACE_LCD_FIT="${FACE_LCD_FIT:-fill}"
export FACE_SINK="${FACE_SINK:-png}"
export RIDER_NO_HW="${RIDER_NO_HW:-1}"

# Walidacja składni (bez HW)
"$TEST_PY" -m compileall -q "$ROOT/services/api_core" "$ROOT/services/api_server.py" "$ROOT/apps/ui/face"

# Minimalny zestaw testów
cd "$ROOT"
"$TEST_PY" -m pytest -q tests/test_face_anim_api.py --timeout=10 --maxfail=1
