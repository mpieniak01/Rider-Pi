#!/usr/bin/env bash
# scripts/bench_detect.sh DUR
set -euo pipefail
export LC_ALL=C

DUR="${1:-10}"
export SKIP_V4L2=1 PREVIEW_ROT="${PREVIEW_ROT:-270}"

MIN_HAAR="${BENCH_MIN_FPS_HAAR:-12}"
MIN_SSD="${BENCH_MIN_FPS_SSD:-4}"
MIN_HYB="${BENCH_MIN_FPS_HYB:-3}"

log() { echo "[bench] $*" >&2; }

num_ge() {  # num_ge VAL MIN -> exit 0 gdy VAL>=MIN
  python3 - "$1" "$2" <<'PY'
import sys
f=float(sys.argv[1]); m=float(sys.argv[2])
sys.exit(0 if f+1e-6>=m else 1)
PY
}

run_and_parse_fps() {
  local name="$1"; shift
  local cmd=( "$@" )
  local status=0
  local out
  out="$(timeout "${DUR}"s "${cmd[@]}" 2>&1 || status=$?)"
  printf "%s\n" "$out" >&2
  # wyciągnij ostatnie "fps=NNN(.M)"
  local fps
  fps="$(printf "%s\n" "$out" | grep -Eo 'fps=[0-9]+(\.[0-9]+)?' | tail -n1 | cut -d= -f2 || true)"
  fps="$(printf "%s" "${fps:-}" | tr -d '[:space:]')"
  if [ -z "$fps" ]; then
    log "$name: no fps found"
    return 2
  fi
  log "$name: fps=$fps"
  printf "%s" "$fps"   # TYLKO liczba na stdout
  return 0
}

# 1) HAAR
fps="$(run_and_parse_fps "HAAR" python3 -u apps/camera/preview_lcd_takeover.py)" || exit 1
num_ge "$fps" "$MIN_HAAR" || { log "FAIL: HAAR < $MIN_HAAR"; exit 1; }
./ops/camera_takeover_kill.sh || true

# 2) SSD
export SSD_EVERY="${SSD_EVERY:-2}" SSD_CLASSES="${SSD_CLASSES:-person}" SSD_SCORE="${SSD_SCORE:-0.55}"
fps="$(run_and_parse_fps "SSD" python3 -u apps/camera/preview_lcd_ssd.py)" || exit 1
num_ge "$fps" "$MIN_SSD" || { log "FAIL: SSD < $MIN_SSD"; exit 1; }
./ops/camera_takeover_kill.sh || true

# 3) HYBRID
export HYBRID_HAAR="${HYBRID_HAAR:-1}"
fps="$(run_and_parse_fps "HYBRID" python3 -u apps/camera/preview_lcd_hybrid.py)" || exit 1
num_ge "$fps" "$MIN_HYB" || { log "FAIL: HYBRID < $MIN_HYB"; exit 1; }

log "PASS: all >= thresholds (HAAR>=$MIN_HAAR, SSD>=$MIN_SSD, HYBRID>=$MIN_HYB)"
