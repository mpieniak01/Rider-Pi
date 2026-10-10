#!/usr/bin/env bash
# Isolated software tests only, with existing project dependencies.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
exec "${PYTHON:-python3}" -m pytest -q tests/test_motion_safety_contract.py tests/test_control_safety_http.py tests/test_test_sandbox.py
