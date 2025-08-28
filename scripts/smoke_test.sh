#!/usr/bin/env bash
# Smoke test: clean → compile → renderers → face(null) → pygame → camera takeover + preview (5s) → power-save
set -Eeuo pipefail
shopt -s lastpipe

# colors
if [ -t 1 ]; then RED='[0;31m'; GRN='[0;32m'; YEL='[0;33m'; BLU='[0;34m'; NC='[0m'; else RED=''; GRN=''; YEL=''; BLU=''; NC=''; fi
log(){ echo -e "${BLU}[i]${NC} $*"; }
ok(){ echo -e "${GRN}[OK]${NC} $*"; }
warn(){ echo -e "${YEL}[..]${NC} $*"; }
fail(){ echo -e "${RED}[ERR]${NC} $*"; exit 1; }

have(){ command -v "$1" >/dev/null 2>&1; }
now(){ date +%F_%H-%M-%S; }

WORKDIR="${1:-$HOME/robot}"; [[ -d "$WORKDIR" ]] || fail "Brak katalogu $WORKDIR"
cd "$WORKDIR"
LOGDIR=logs; mkdir -p "$LOGDIR"
TS="$(now)"; SUMMARY="$LOGDIR/smoke_summary_$TS.txt"; : > "$SUMMARY"

TO_RC=0
run_to(){ local s="$1"; shift; if have timeout; then timeout -k 5 "$s" "$@"; TO_RC=$?; else ("$@" & pid=$!; sleep "$s"; kill "$pid" 2>/dev/null || true; TO_RC=$?); fi; }

PASS=(); WARN=(); FAIL=()
step_ok(){ ok "$1"; PASS+=("$1"); echo "PASS: $1" >> "$SUMMARY"; }
step_warn(){ warn "$1"; WARN+=("$1"); echo "WARN: $1" >> "$SUMMARY"; }
step_fail(){ warn "$1"; FAIL+=("$1"); echo "FAIL: $1" >> "$SUMMARY"; }

# power-save trap (mocniejszy, kilkukrotny)
power_save(){
  log "Power-save: ubijam testy i gaszę wyświetlacz…"
  for i in 1 2 3 4 5; do
    pkill -TERM -f 'apps\.ui\.face|apps\.camera|libcamera-|rpicam-|picamera2|xgo' 2>/dev/null || true
    sleep 0.3
    pkill -KILL -f 'apps\.ui\.face|apps\.camera|libcamera-|rpicam-|picamera2|xgo' 2>/dev/null || true
    for n in /dev/media* /dev/video*; do fuser -k "$n" 2>/dev/null || true; done
    # OFF LCD + blank FB + DPMS Off
    sudo -n python3 scripts/lcdctl.py off >/dev/null 2>&1 || sudo python3 scripts/lcdctl.py off
    for fb in /sys/class/graphics/fb*/blank; do echo 1 | sudo tee "$fb" >/dev/null 2>&1 || true; done
    for dp in /sys/class/drm/*/dpms; do echo Off | sudo tee "$dp" >/dev/null 2>&1 || true; done
    sleep 0.5
  done
  ok "Power-save completed"
}
trap power_save EXIT

log "Repo: $WORKDIR"; log "Logi: $LOGDIR (summary: $(basename "$SUMMARY"))"

# 1) clean
log "Czyszczę __pycache__ …"; find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true; step_ok "clean __pycache__"

# 2) compileall
log "Kompiluję moduły (compileall) …"
if python3 - <<'PY'
import compileall, sys
ok = compileall.compile_dir('.', quiet=1, force=False)
sys.exit(0 if ok else 1)
PY
then step_ok "compileall"; else step_warn "compileall (są błędy kompilacji; patrz log)"; fi

# 3) renderer import
log "Test importu rendererów …"
if python3 - <<'PY'
try:
    import apps.ui.face_renderers as fr
    names = [n for n in dir(fr) if n.endswith('Renderer')]
    print('Dostępne:', names)
    assert 'BaseRenderer' in names
except Exception as e:
    print('FAIL:', e); raise
PY
then step_ok "renderers import"; else step_fail "renderers import"; fi

# 4) face null (5s)
log "Uruchamiam apps.ui.face (FACE_BACKEND=null) na 5 sekund …"
run_to 5 env FACE_BACKEND=null FACE_BENCH=1 python3 -m apps.ui.face > "$LOGDIR/face_null_$TS.log" 2>&1 || true
if (( TO_RC==0 || TO_RC==124 )); then step_ok "face (null backend)"; else step_fail "face (null backend)"; fi

# 5) pygame (5s)
log "Pygame test – 5s …"
run_to 5 env FACE_BACKEND=pygame FACE_BENCH=1 python3 -m apps.ui.face > "$LOGDIR/face_pygame_$TS.log" 2>&1 || true
if (( TO_RC==0 || TO_RC==124 )); then step_ok "face (pygame)"; else step_fail "face (pygame)"; fi

# 6) killer / takeover-pre
log "Przygotowuję kamerę/LCD (takeover-pre)…"
bash scripts/camera_takeover_kill.sh | tee "$LOGDIR/takeover_pre_$TS.log" >/dev/null

# 7) camera preview (Picamera2, 5s)
log "Uruchamiam podgląd kamery (5s)…"
run_to 5 sudo SKIP_V4L2=1 PREVIEW_ROT=270 PREVIEW_WARMUP=6 VISION_HUMAN=1 python3 -m apps.camera > "$LOGDIR/camera_preview_$TS.log" 2>&1 || true
# akceptuj też statusy 137 (SIGKILL) i 143 (SIGTERM), które czasem zwraca timeout
if (( TO_RC==0 || TO_RC==124 || TO_RC==137 || TO_RC==143 )); then step_ok "camera preview (LCD)"; else step_fail "camera preview (LCD)"; fi

# 8) lock check (druga instancja ma się nie uruchomić)
log "Sprawdzam lock (druga instancja)…"
run_to 2 sudo SKIP_V4L2=1 python3 -m apps.camera > "$LOGDIR/camera_lock_$TS.log" 2>&1 || true
if grep -q "inna instancja" "$LOGDIR/camera_lock_$TS.log" 2>/dev/null; then step_ok "lock ok"; else step_warn "lock: brak komunikatu (sprawdź log)"; fi

# summary
echo; echo "================ SMOKE SUMMARY ($TS) ================"
for s in "${PASS[@]}"; do echo -e "${GRN}✔${NC} $s"; done
for s in "${WARN[@]}"; do echo -e "${YEL}●${NC} $s"; done
for s in "${FAIL[@]}"; do echo -e "${RED}✘${NC} $s"; done
TOTAL_P=${#PASS[@]}; TOTAL_W=${#WARN[@]}; TOTAL_F=${#FAIL[@]}
if (( TOTAL_F==0 )); then ok "Test zakończony: PASS=$TOTAL_P, WARN=$TOTAL_W, FAIL=$TOTAL_F"; exit 0; else warn "Test zakończony: PASS=$TOTAL_P, WARN=$TOTAL_W, FAIL=$TOTAL_F"; exit 1; fi