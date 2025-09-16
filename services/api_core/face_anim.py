from __future__ import annotations
from typing import Dict, Any
from types import SimpleNamespace
import threading, time

# Renderer nowej buźki (snapshot do PNG w pętli; LCD dodamy później)
from apps.ui.face.renderer import FaceRenderer

ALLOWED = {"neutral", "happy", "sad", "blink"}

def _norm_expr(v: str) -> str:
    v = str(v or "neutral").strip().lower()
    return v if v in ALLOWED else "neutral"

# Globalny, prosty stan animacji utrzymywany w pamięci procesu
STATE: Dict[str, Any] = {
    "playing": False,
    "running": False,
    "expr": "neutral",
    "fps": 20,
    "started_ts": None,
    "last_ts": None,
}

# ──────────────────────────────────────────────────────────────────────────────
# Animator: pętla w tle sterowana /face/play|/stop; na razie renderuje PNG bytes
# (możesz opcjonalnie zapisywać do /tmp/face_runtime.png dla debugowania)
# ──────────────────────────────────────────────────────────────────────────────
class _Animator:
    def __init__(self):
        self._thr: threading.Thread | None = None
        self._stop = threading.Event()
        self._renderer: FaceRenderer | None = None

    def start(self):
        if self._thr and self._thr.is_alive():
            return
        self._stop.clear()
        self._thr = threading.Thread(target=self._loop, name="face-anim", daemon=True)
        self._thr.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        try:
            # docelowo: cfg z modelu; na razie pusty dict jest OK
            self._renderer = FaceRenderer(cfg={}, size=240, guide=False, quality="fast")
        except Exception:
            self._renderer = None

        STATE["running"] = True
        STATE["started_ts"] = time.time()
        last = time.time()

        while not self._stop.is_set() and STATE.get("playing", False):
            fps = max(1, min(60, int(STATE.get("fps", 20) or 20)))
            expr = _norm_expr(STATE.get("expr"))
            # Minimalny FaceState „lookalike” – wystarcza do rysunku
            face_state = SimpleNamespace(expr=expr, blink=False, pupil=0, tilt=0)

            try:
                if self._renderer:
                    png = self._renderer.render_png_bytes(face_state)
                    # DEBUG (opcjonalnie): podejrzenie ostatniej klatki
                    # with open("/tmp/face_runtime.png", "wb") as f:
                    #     f.write(png)
            except Exception:
                # pętla ma żyć dalej, nawet jeśli jedna klatka się wywali
                pass

            STATE["last_ts"] = time.time()
            dt = 1.0 / fps
            # zachowaj mniej więcej zadany FPS
            time.sleep(max(0.0, dt - (STATE["last_ts"] - last)))
            last = time.time()

        STATE["running"] = False

_anim = _Animator()

# ──────────────────────────────────────────────────────────────────────────────
# Czyste funkcje biznesowe wywoływane z services/api_server.py
# Zwracają czyste dicty; HTTP/JSON/CORS dodaje serwer.
# ──────────────────────────────────────────────────────────────────────────────
def play(payload: Dict[str, Any]) -> Dict[str, Any]:
    expr = _norm_expr(payload.get("expr"))
    fps = max(1, min(60, int(payload.get("fps", STATE.get("fps", 20) or 20))))
    STATE.update({"expr": expr, "fps": fps, "playing": True})
    _anim.start()
    return {"ok": True, "state": STATE}

def stop(_payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    STATE["playing"] = False
    _anim.stop()
    return {"ok": True, "state": STATE}

def get_state() -> Dict[str, Any]:
    return {"ok": True, "state": STATE}


