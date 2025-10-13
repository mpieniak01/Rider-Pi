#!/usr/bin/env bash
# Rider-Pi — unified splash wrapper (xgo/pygame/auto) with Makefile fallback + optional logo pre-slide
set -euo pipefail

ROOT="${ROBOT_ROOT:-/home/pi/robot}"
ROTATE="${SPLASH_ROTATE:-270}"
SECONDS="${SPLASH_SECONDS:-10}"
CLEAR="${SPLASH_CLEAR:-0}"
USE="${SPLASH_USE:-auto}"

PY="${PYTHON:-/usr/bin/python3}"
PY_IMPL="${ROOT}/scripts/sys_splash-info.py"
LEGACY_PY="${ROOT}/scripts/splash_device_info.py"   # dawna nazwa (jeśli istnieje)

log(){ echo "[splash-wrapper] $*"; }

# ─────────────────────────────────────────────────────────────────────────────
# [NOWE] Pre-slide: logo (opcjonalnie)
# Ustaw zmienne środowiskowe:
#   SPLASH_LOGO=/home/pi/robot/data/splash_logo.png
#   SPLASH_LOGO_SECONDS=2   (domyślnie 2)
# Logo zostanie obrócone wg SPLASH_ROTATE i pokazane tym samym prezenterem co status.
# Błędy w tym kroku są ignorowane (kontynuujemy do status splash).
# ─────────────────────────────────────────────────────────────────────────────
if [[ -n "${SPLASH_LOGO:-}" && -f "${SPLASH_LOGO}" ]]; then
  log "logo pre-slide: ${SPLASH_LOGO} (${SPLASH_LOGO_SECONDS:-2}s, rot=${ROTATE})"
  set +e
  "${PY}" - <<'PY' 2>/dev/null || true
import os, time, importlib.util
from pathlib import Path

logo_path = os.environ.get("SPLASH_LOGO")
rotate = int(os.environ.get("SPLASH_ROTATE","270"))
seconds = float(os.environ.get("SPLASH_LOGO_SECONDS","2"))
root = os.environ.get("ROBOT_ROOT","/home/pi/robot")
py_impl = os.path.join(root, "scripts", "sys_splash-info.py")

if not (logo_path and Path(logo_path).exists()):
    raise SystemExit(0)

# PIL (Pillow) jest używany także w status splash, więc zakładamy, że jest dostępny.
from PIL import Image

# Spróbuj załadować klasę Presenter z sys_splash-info.py, żeby użyć identycznej ścieżki renderu.
Presenter = None
try:
    spec = importlib.util.spec_from_file_location("sys_splash_info_impl", py_impl)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    Presenter = getattr(mod, "Presenter", None)
except Exception:
    Presenter = None

if Presenter is None:
    # Nie udało się – trudno, wychodzimy po cichu (wrapper przejdzie dalej do status splash).
    raise SystemExit(0)

im = Image.open(logo_path).convert("RGB")
if rotate in (90,180,270):
    im = im.rotate(rotate, expand=True)

try:
    p = Presenter()
    p.show_image(im)
    time.sleep(seconds)
except Exception:
    # Ignoruj problemy z LCD – przejdziemy do status splash
    pass
PY
  set -e
fi

# ─────────────────────────────────────────────────────────────────────────────
# Główny splash statusu (bez zmian funkcjonalnych)
if [[ -f "${PY_IMPL}" ]]; then
  log "python splash -> ${PY_IMPL} (rotate=${ROTATE}, seconds=${SECONDS}, clear=${CLEAR}, use=${USE})"
  env SPLASH_ROTATE="${ROTATE}" SPLASH_SECONDS="${SECONDS}" SPLASH_CLEAR="${CLEAR}" SPLASH_USE="${USE}" \
    "${PY}" "${PY_IMPL}"
elif [[ -f "${LEGACY_PY}" ]]; then
  log "python legacy splash -> ${LEGACY_PY} (rotate=${ROTATE}, seconds=${SECONDS}, clear=${CLEAR}, use=${USE})"
  env SPLASH_ROTATE="${ROTATE}" SPLASH_SECONDS="${SECONDS}" SPLASH_CLEAR="${CLEAR}" SPLASH_USE="${USE}" \
    "${PY}" "${LEGACY_PY}"
else
  log "no python splash found, fallback to Makefile testcard (seconds=${SECONDS})"
  # Fallback: kolorowa plansza na LCD
  FACE_LCD_ROTATE="${ROTATE}" FACE_LCD_SPI_HZ="${FACE_LCD_SPI_HZ:-32000000}" \
    sudo -E make -C "${ROOT}" face-testcard || true
  sleep "${SECONDS}"
  if [[ "${CLEAR}" == "1" ]]; then
    make -C "${ROOT}" lcd-black || true
  fi
fi
