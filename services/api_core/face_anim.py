from __future__ import annotations
from typing import Dict, Any
from types import SimpleNamespace
import threading
import time

# Renderer nowej buźki (snapshot do PNG w pętli; LCD dodamy później)
from apps.ui.face.renderer import FaceRenderer

# ── Konfiguracja/kontrakt plików wyjściowych ─────────────────────────────────
OUT_LATEST = "/tmp/face_latest.png"         # nowy kontrakt (DoD)
OUT_LEGACY = "/tmp/face_render_loop.png"    # zgodność wstecz

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
    "frame_count": 0,
}


# ──────────────────────────────────────────────────────────────────────────────
# Animator: pętla w tle sterowana /face/play|/stop; renderuje do PNG bytes
# ──────────────────────────────────────────────────────────────────────────────
class _Animator:
    def __init__(self):
        self._thr: threading.Thread | None = None
        self._stop = threading.Event()
        self._renderer: FaceRenderer | None = None

    def start(self):
        # uruchom tylko jeśli nie działa
        if self._thr and self._thr.is_alive():
            return
        self._stop.clear()
        self._thr = threading.Thread(target=self._loop, name="face-anim", daemon=True)
        self._thr.start()

    def stop(self):
        # sygnał zatrzymania — pętla sprawdza zarówno flagę, jak i STATE["playing"]
        self._stop.set()

    def join(self, timeout: float | None = None):
        t = self._thr
        if t and t.is_alive():
            t.join(timeout=timeout)

    def _loop(self):
        try:
            # docelowo: cfg z modelu; na razie pusty dict jest OK
            self._renderer = FaceRenderer(cfg={}, size=240, guide=False, quality="fast")
        except Exception:
            self._renderer = None

        STATE["running"] = True
        # nie nadpisuj started_ts przy resume tego samego „play”
        if not STATE.get("started_ts"):
            STATE["started_ts"] = time.time()

        last_tick = time.time()

        while (not self._stop.is_set()) and STATE.get("playing", False):
            fps = max(1, min(60, int(STATE.get("fps", 20) or 20)))
            expr = _norm_expr(STATE.get("expr"))
            # Minimalny FaceState „lookalike” – wystarcza do rysunku
            face_state = SimpleNamespace(expr=expr, blink=False, pupil=0, tilt=0)

            try:
                if self._renderer:
                    png = self._renderer.render_png_bytes(face_state)
                    # Zapisz finalną klatkę (kontrakt DoD + zgodność)
                    try:
                        with open(OUT_LATEST, "wb") as f:
                            f.write(png)
                        try:
                            with open(OUT_LEGACY, "wb") as f2:
                                f2.write(png)
                        except Exception:
                            pass  # legacy opcjonalne
                    except Exception:
                        pass  # zapis nie może zabić pętli
            except Exception:
                # pętla ma żyć dalej, nawet jeśli jedna klatka się wywali
                pass

            # Aktualizuj stan
            STATE["last_ts"] = time.time()
            STATE["frame_count"] = int(STATE.get("frame_count") or 0) + 1

            # zachowaj mniej więcej zadany FPS
            dt = 1.0 / fps
            sleep_left = dt - (STATE["last_ts"] - last_tick)
            if sleep_left > 0:
                # krótsze spanie = szybsze reagowanie na stop()
                time.sleep(min(sleep_left, 0.05))
                # dociągnij resztę (jeśli była potrzeba)
                remain = sleep_left - 0.05
                if remain > 0:
                    time.sleep(remain)
            last_tick = time.time()

        STATE["running"] = False


_anim = _Animator()


# ──────────────────────────────────────────────────────────────────────────────
# Czyste funkcje biznesowe (używane także przez „view” shimy)
# ──────────────────────────────────────────────────────────────────────────────
def play(payload: Dict[str, Any]) -> Dict[str, Any]:
    expr = _norm_expr(payload.get("expr"))
    fps = max(1, min(60, int(payload.get("fps", STATE.get("fps", 20) or 20))))
    STATE.update(
        {
            "expr": expr,
            "fps": fps,
            "playing": True,
            "started_ts": time.time(),
            "frame_count": 0,
            "last_ts": None,
        }
    )
    _anim.start()
    return {"ok": True, "state": STATE}


def stop(_payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    STATE["playing"] = False
    _anim.stop()
    # daj pętli do 0.5 s na eleganckie zejście (DoD: stop < 0.5 s)
    _anim.join(timeout=0.5)
    if STATE.get("running") and (_anim._thr and _anim._thr.is_alive()):
        # jeśli nie zdążył się wyłączyć, zostaw „running” zgodnie z realnym stanem
        # (zwykle dojdzie do False za moment)
        pass
    return {"ok": True, "state": STATE}


def get_state() -> Dict[str, Any]:
    return {"ok": True, "state": STATE}


# ──────────────────────────────────────────────────────────────────────────────
# Flask view shims: możesz bezpośrednio rejestrować je w app.add_url_rule(...)
# (dzięki temu ten moduł pozostaje samowystarczalny)
# ──────────────────────────────────────────────────────────────────────────────
def post_play():
    from flask import request, make_response, jsonify

    if request.method == "OPTIONS":
        return make_response("", 204)
    payload = request.get_json(silent=True) or {}
    return jsonify(play(payload))


def post_stop():
    from flask import request, make_response, jsonify

    if request.method == "OPTIONS":
        return make_response("", 204)
    return jsonify(stop({}))