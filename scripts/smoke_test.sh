#!/usr/bin/env bash
# Rider-Pi: minimal smoke test + clean LCD shutdown via scripts/lcdctl.py
# Usage:
#   bash scripts/smoke_test.sh                # test $HOME/robot
#   bash scripts/smoke_test.sh /path/to/repo  # test specific directory
#
# Env:
#   RUN_PYGAME=1   – force pygame step even without DISPLAY

set -Eeuo pipefail
shopt -s lastpipe

# --- tiny logger --------------------------------------------------------------
if [ -t 1 ]; then RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[0;33m'; BLU='\033[0;34m'; NC='\033[0m'; else RED=''; GRN=''; YEL=''; BLU=''; NC=''; fi
log(){ echo -e "${BLU}[i]${NC} $*"; }
ok(){  echo -e "${GRN}[OK]${NC} $*"; }
warn(){ echo -e "${YEL}[..]${NC} $*"; }
fail(){ echo -e "${RED}[ERR]${NC} $*"; exit 1; }
now(){ date +%F_%H-%M-%S; }
have(){ command -v "$1" >/dev/null 2>&1; }

# --- repo path ---------------------------------------------------------------
DEFAULT_REPO="$HOME/robot"
WORKDIR="${1:-$DEFAULT_REPO}"
[[ -d "$WORKDIR" ]] || fail "Brak katalogu: $WORKDIR"
cd "$WORKDIR"

LOGDIR="logs"; mkdir -p "$LOGDIR"; TS="$(now)"; SUMMARY="$LOGDIR/smoke_summary_$TS.txt"; : > "$SUMMARY"
log "Repo: $WORKDIR"; log "Logi: $LOGDIR (summary: $(basename "$SUMMARY"))"

# --- cleanup on exit: kill face + blank LCD via lcdctl -----------------------
cleanup(){
  log "Cleanup: kill face + LCD OFF"
  # best-effort kill
  pkill -TERM -f "python3 -m apps.ui.face" 2>/dev/null || true
  pkill -TERM -f "apps/ui/face.py"         2>/dev/null || true
  sleep 0.2
  pkill -KILL -f "python3 -m apps.ui.face" 2>/dev/null || true
  pkill -KILL -f "apps/ui/face.py"         2>/dev/null || true
  # turn the 2" panel fully off (sleep + backlight off)
  if [[ -f scripts/lcdctl.py ]]; then
    sudo -n python3 scripts/lcdctl.py off >/dev/null 2>&1 || sudo python3 scripts/lcdctl.py off || true
  fi
}
trap cleanup EXIT

# --- helper: timeout runner --------------------------------------------------
TO_RC=0
run_to(){ local secs="$1"; shift; if have timeout; then timeout -k 2 "$secs" "$@"; TO_RC=$?; else ( "$@" & pid=$!; ); sleep "$secs" || true; kill "$pid" 2>/dev/null || true; TO_RC=124; fi; }

PASS=(); FAIL=(); WARN=()
step_ok(){   ok   "$1"; PASS+=("$1"); echo "PASS: $1" >> "$SUMMARY"; }
step_fail(){ warn "$1"; FAIL+=("$1"); echo "FAIL: $1" >> "$SUMMARY"; }
step_warn(){ warn "$1"; WARN+=("$1"); echo "WARN: $1" >> "$SUMMARY"; }

# --- step 1: env info --------------------------------------------------------
uname -a | tee -a "$SUMMARY" >/dev/null; python3 -V | tee -a "$SUMMARY" >/dev/null || fail "python3?"

# --- step 2: clean __pycache__ ----------------------------------------------
log "Czyszczę __pycache__ ..."; find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true; step_ok "clean __pycache__"

# --- step 3: compileall (warn-only) -----------------------------------------
log "Kompiluję moduły (compileall) ..."
if python3 - <<'PY'
import compileall, sys
ok = compileall.compile_dir('.', quiet=1, force=False)
sys.exit(0 if ok else 1)
PY
then step_ok "compileall"; else step_warn "compileall (są błędy, patrz konsolę)"; fi

# --- step 4: renderer import -------------------------------------------------
log "Test importu rendererów ..."
if python3 - <<'PY'
try:
    import apps.ui.face_renderers as fr
    ok = hasattr(fr, 'BaseRenderer')
    print('Dostępne:', [n for n in dir(fr) if n.endswith('Renderer')])
except Exception as e:
    print('Import fail:', e); ok=False
import sys; sys.exit(0 if ok else 1)
PY
then step_ok "renderers import"; else step_fail "renderers import"; fi

# --- step 5: face (null) -----------------------------------------------------
log "Uruchamiam apps.ui.face (FACE_BACKEND=null) na 5 sekund ..."
run_to 5 env FACE_BACKEND=null FACE_BENCH=1 python3 -m apps.ui.face > "$LOGDIR/face_null_$TS.log" 2>&1 || true
(( TO_RC == 0 || TO_RC == 124 )) && step_ok "face (null backend)" || step_fail "face (null backend)"

# --- step 6: pygame (optional) -----------------------------------------------
if [[ -n "${DISPLAY:-}" ]] || [[ "${RUN_PYGAME:-0}" == "1" ]]; then
  log "Pygame test – 5s ..."
  run_to 5 env FACE_BACKEND=pygame FACE_BENCH=1 python3 -m apps.ui.face > "$LOGDIR/face_pygame_$TS.log" 2>&1 || true
  (( TO_RC == 0 || TO_RC == 124 )) && step_ok "face (pygame)" || step_fail "face (pygame)"
else
  step_warn "Pominięto test pygame (brak DISPLAY). Ustaw RUN_PYGAME=1 aby wymusić."
fi

# --- summary -----------------------------------------------------------------
echo; echo "================ SMOKE SUMMARY ($TS) ================"
for s in "${PASS[@]}"; do echo -e "${GRN}✔${NC} $s"; done
for s in "${WARN[@]}"; do echo -e "${YEL}●${NC} $s"; done
for s in "${FAIL[@]}"; do echo -e "${RED}✘${NC} $s"; done
TOTAL_P=${#PASS[@]}; TOTAL_W=${#WARN[@]}; TOTAL_F=${#FAIL[@]}
(( TOTAL_F == 0 )) && ok "Test zakończony: PASS=${TOTAL_P}, WARN=${TOTAL_W}, FAIL=${TOTAL_F}" || warn "Test zakończony: PASS=${TOTAL_P}, WARN=${TOTAL_W}, FAIL=${TOTAL_F}"

# lcdctl.py OFF zostanie wykonane automatycznie w trap EXIT

