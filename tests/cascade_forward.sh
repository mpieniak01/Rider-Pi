#!/usr/bin/env bash
# Physical actuator probes are never part of automatic diagnostics.
set -euo pipefail
printf '%s\n' 'Legacy movement sequence disabled. Use scripts/manual_motion-probe.py for one operator-approved attempt.' >&2
exit 2
