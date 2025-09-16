from __future__ import annotations

import os
from pathlib import Path
OUT_LATEST = os.environ.get('FACE_LATEST_PATH','/tmp/face_latest.png')
from typing import Dict, Any
from types import SimpleNamespace
import threading
import time

# Renderer nowej buźki (snapshot do PNG w pętli; LCD dodamy później)

from apps.ui.face.renderer import FaceRenderer
from PIL import Image
import os
from typing import Optional

# --- SINKI ---
class FaceSink:
    def present(self, img: Image.Image):
        raise NotImplementedError
    def present_png(self, data: bytes):
        raise NotImplementedError

class NullSink(FaceSink):
    def present(self, img: Image.Image):
        pass
    def present_png(self, data: bytes):
        pass

class FileSink(FaceSink):
    def __init__(self, path=OUT_LATEST):
        self.path = path
    def present(self, img: Image.Image):
        img.save(self.path, 'PNG')
    def present_png(self, data: bytes):
        with open(self.path, 'wb') as f:
            f.write(data)

class LcdNotAvailable(Exception):
    pass

class LcdFaceSink(FaceSink):
    def __init__(self, **kwargs):
        try:
            from apps.hw.sink_lcd import SinkLCD
        except ImportError:
            raise LcdNotAvailable("LCD driver not importable")
        try:
            self.lcd = SinkLCD(**kwargs)
        except Exception as e:
            raise LcdNotAvailable(f"LCD init failed: {e}")
    def present(self, img: Image.Image):
        try:
            self.lcd.push_auto(img)
        except Exception as e:
            raise LcdNotAvailable(f"LCD present failed: {e}")
    def present_png(self, data: bytes):
        from io import BytesIO
        img = Image.open(BytesIO(data))
        self.present(img)

def get_sink(env: dict, payload: Optional[dict]=None) -> FaceSink:
    sink_name = None
    if payload and 'sink' in payload:
        sink_name = payload['sink']
    else:
        sink_name = env.get('FACE_SINK')
    if sink_name == 'file':
        return FileSink()
    elif sink_name == 'lcd':
        try:
            return LcdFaceSink(
                rotate=int(env.get('FACE_LCD_ROTATE', 0)),
                spi_hz=int(env.get('FACE_LCD_SPI_HZ', 32000000)),
                method=env.get('FACE_LCD_DRIVER', 'auto')
            )
        except Exception as e:
            raise LcdNotAvailable(str(e))
    else:
        return NullSink()

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
            self._renderer = FaceRenderer(cfg={}, size=240, guide=False, quality="fast")
        except Exception:
            self._renderer = None

        # Wybierz sink na podstawie ENV i ostatniego payloadu play
        env = dict(os.environ)
        try:
            # Przechowuj ostatni payload w stanie (jeśli play() go ustawi)
            payload = STATE.get("_last_payload")
        except Exception:
            payload = None
        try:
            sink = get_sink(env, payload)
        except LcdNotAvailable as e:
            # LCD nie dostępny — sygnalizuj błąd i zatrzymaj animację
            STATE["playing"] = False
            STATE["running"] = False
            STATE["error"] = str(e)
            return
        except Exception as e:
            sink = NullSink()

        STATE["running"] = True
        if not STATE.get("started_ts"):
            STATE["started_ts"] = time.time()

        last_tick = time.time()

        while (not self._stop.is_set()) and STATE.get("playing", False):
            fps = max(1, min(60, int(STATE.get("fps", 20) or 20)))
            expr = _norm_expr(STATE.get("expr"))
            face_state = SimpleNamespace(expr=expr, blink=False, pupil=0, tilt=0)

            try:
                if self._renderer:
                    img = self._renderer.render_image(face_state)
                    try:
                        sink.present(img)
                    except LcdNotAvailable as e:
                        STATE["playing"] = False
                        STATE["running"] = False
                        STATE["error"] = str(e)
                        break
                    except Exception:
                        pass  # nie zabijaj pętli na błędzie sinka
                    # FileSink nadal zapisuje PNG (kontrakt DoD + zgodność)
                    try:
                        img.save(OUT_LATEST, "PNG")
                        try:
                            img.save(OUT_LEGACY, "PNG")
                        except Exception:
                            pass
                    except Exception:
                        pass
            except Exception:
                pass

            STATE["last_ts"] = time.time()
            STATE["frame_count"] = int(STATE.get("frame_count") or 0) + 1

            dt = 1.0 / fps
            sleep_left = dt - (STATE["last_ts"] - last_tick)
            if sleep_left > 0:
                time.sleep(min(sleep_left, 0.05))
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
    # zapamiętaj ostatni payload do wyboru sinka
    STATE["_last_payload"] = payload.copy() if payload else None
    STATE.update(
        {
            "expr": expr,
            "fps": fps,
            "playing": True,
            "started_ts": time.time(),
            "frame_count": 0,
            "last_ts": None,
            "error": None,
        }
    )
    _anim.start()
    # LCD error: zwróć 503 jeśli nie można uruchomić LCD
    if STATE.get("error") and (payload.get("sink") == "lcd" or os.environ.get("FACE_SINK") == "lcd"):
        return {"ok": False, "status": 503, "error": STATE["error"]}
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