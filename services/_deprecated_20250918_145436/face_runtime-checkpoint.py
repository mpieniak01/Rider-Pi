# services/api_core/face_runtime.py (propozycja)
import threading, time
from apps.ui.face.renderer import FaceRenderer
from services.api_core.face_anim import STATE, _norm_expr

class Animator:
    def __init__(self):
        self._thr = None
        self._stop = threading.Event()
        self._renderer = FaceRenderer(cfg={}, size=240, guide=False, quality="fast")

    def start(self):
        if self._thr and self._thr.is_alive(): return
        self._stop.clear()
        self._thr = threading.Thread(target=self._loop, name="face-anim", daemon=True)
        self._thr.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        last = time.time()
        while not self._stop.is_set() and STATE.get("playing"):
            fps = max(1, int(STATE.get("fps", 20)))
            expr = _norm_expr(STATE.get("expr"))
            # TODO: zbuduj FaceState z modelu; tymczasowo minimalny obiekt:
            from types import SimpleNamespace
            face_state = SimpleNamespace(expr=expr, blink=False, pupil=0, tilt=0)

            try:
                png = self._renderer.render_png_bytes(face_state)
                # TODO sink: LCD / fallback do pliku:
                # with open("/tmp/face_runtime.png", "wb") as f: f.write(png)
            except Exception:
                pass

            STATE["last_ts"] = time.time()
            dt = 1.0 / fps
            delay = max(0.0, dt - (STATE["last_ts"] - last))
            time.sleep(delay)
            last = time.time()

animator = Animator()
