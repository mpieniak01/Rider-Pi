#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apps/ui/face.py — „twarz” robota: orchestracja (BUS, model, pętla główna).
Renderery i rysowanie są w apps/ui/face_renderers.py.

Uruchamianie (LCD):
  FACE_BACKEND=lcd FACE_BENCH=1 FACE_GUIDE=1 python3 -m apps.ui.face
"""
from __future__ import annotations
import os, sys, time, math, random, threading, queue, platform, atexit, signal
from time import perf_counter
from typing import Optional

# --- ścieżki projektu / bus ---------------------------------------------------
PROJ_ROOT = "/home/pi/robot"
if PROJ_ROOT not in sys.path:
    sys.path.insert(0, PROJ_ROOT)

try:
    from common.bus import BusSub, BusPub  # type: ignore
except Exception:
    # awaryjne stuby: pozwalają uruchomić UI bez gotowego busa
    class _StubSub:
        def __init__(self, *_a, **_k): pass
        def recv(self, timeout_ms=0): time.sleep(timeout_ms/1000.0); return None, None
    class _StubPub:
        def __init__(self, *_a, **_k): pass
        def send(self, *_a, **_k): pass
    BusSub = _StubSub  # type: ignore
    BusPub = _StubPub  # type: ignore

from apps.ui.face_renderers import BaseRenderer, LCDRenderer, TKRenderer, FaceConfig

# --- konfiguracja z ENV -------------------------------------------------------
BACKEND_ENV  = os.environ.get("FACE_BACKEND", "auto").lower()
FPS          = int(os.environ.get("FACE_FPS", "30"))
AUTO_FPS     = int(os.environ.get("FACE_AUTO_FPS", "1")) != 0
BENCH        = int(os.environ.get("FACE_BENCH", "1")) != 0
GUIDE        = int(os.environ.get("FACE_GUIDE", "1")) != 0
BROW_CAPS    = int(os.environ.get("FACE_BROW_CAPS", "0")) != 0
BROW_STYLE   = os.environ.get("FACE_BROW_STYLE", "classic").strip().lower()
QUALITY      = os.environ.get("FACE_QUALITY", "fast").strip().lower()

def _f(env, default, lo=None, hi=None):
    try:
        v = float(os.environ.get(env, str(default)))
        if lo is not None: v = max(lo, v)
        if hi is not None: v = min(hi, v)
        return v
    except Exception:
        return default

BROW_TAPER = _f("FACE_BROW_TAPER", 0.5, 0.0, 1.0)
BROW_Y_K   = _f("FACE_BROW_YK",    0.21, 0.14, 0.30)
BROW_H_K   = _f("FACE_BROW_HK",    0.09, 0.06, 0.16)
MOUTH_Y_K  = _f("FACE_MOUTH_YK",   0.215, 0.18, 0.28)
HEAD_KY    = _f("FACE_HEAD_KY",    1.04, 0.90, 1.20)

LCD_DO_INIT  = bool(int(os.environ.get("FACE_LCD_DO_INIT", "1")))
LCD_ROTATE   = int(os.environ.get("FACE_LCD_ROTATE", "270"))
_SPI_ENV     = os.environ.get("FACE_LCD_SPI_HZ", "").strip()
LCD_SPI_HZ   = None if not _SPI_ENV else max(1_000_000, int(_SPI_ENV))

# takeover
LCD_TAKEOVER_MODE = os.environ.get("FACE_LCD_TAKEOVER_MODE", "both").lower().strip()
LCD_KILL_RE       = os.environ.get("FACE_LCD_KILL_RE", r"remix\.py|mian\.py|main\.py|demo.*\.py|app_.*\.py")

# lock
LOCK_PATH     = "/tmp/rider_face.lcd.lock"
LOCK_OVERRIDE = int(os.environ.get("FACE_LOCK_OVERRIDE", "0")) != 0

COLORS = {
    "idle":        (30, 58, 138),
    "wake":        (245, 158, 11),
    "record":      (249, 115, 22),
    "process":     (124, 58, 237),
    "speak":       (16, 185, 129),
    "low_battery": (239, 68, 68),
}
APP_VER = "0.3.0"

# --- PID-lock -----------------------------------------------------------------
def _pid_alive(pid: int) -> bool:
    try: os.kill(pid, 0); return True
    except OSError: return False

def _cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().decode("utf-8", "ignore").replace("\x00", " ")
    except Exception:
        return ""

def acquire_lock():
    if LOCK_OVERRIDE:
        try: os.unlink(LOCK_PATH)
        except Exception: pass

    old_pid = None
    if os.path.exists(LOCK_PATH):
        try:
            with open(LOCK_PATH, "r") as f:
                old_pid = int((f.read().strip() or "0"))
        except Exception:
            old_pid = None

    if old_pid:
        alive = _pid_alive(old_pid)
        same  = "apps/ui/face" in _cmdline(old_pid)
        if not alive or not same:
            try: os.unlink(LOCK_PATH)
            except Exception: pass
        else:
            try:
                os.kill(old_pid, signal.SIGTERM)
                for _ in range(40):
                    if not _pid_alive(old_pid): break
                    time.sleep(0.05)
            except Exception:
                pass
            if _pid_alive(old_pid):
                print(f"[face] stara instancja (PID {old_pid}) wciąż żyje — kończę.", flush=True)
                sys.exit(0)

    with open(LOCK_PATH, "w") as f:
        f.write(str(os.getpid()))

def release_lock():
    try: os.unlink(LOCK_PATH)
    except Exception: pass

# --- model stanu --------------------------------------------------------------
class FaceModel:
    def __init__(self):
        self.state = "idle"
        self.user_text = ""
        self.assistant_text = ""
        self.assist_speaking = False
        # mimika z busa
        self.expr: Optional[str] = None
        self.expr_intensity: float = 0.7
        # mruganie
        self.last_blink = time.time()
        self.next_blink_after = random.uniform(5.0, 8.0)
        self.blink_close_ms = 0.090
        self.blink_after_ms = 0.040
        # mowa
        self.speak_phase = 0.0
        # sakkady (gaze offset, px)
        self.gaze_dx = 0.0

    def trigger_blink(self):
        self.last_blink = time.time()

    def tick(self, dt: float):
        now = time.time()
        if now - self.last_blink > self.next_blink_after:
            self.last_blink = now
            self.next_blink_after = random.uniform(5.0, 8.0)
            self.gaze_dx += random.uniform(-4.0, 4.0)
        self.gaze_dx *= 0.86
        if self.assist_speaking or self.state == "speak":
            self.speak_phase += dt * 10.0
        else:
            self.speak_phase *= 0.9

    def blink_mul(self) -> float:
        t = time.time() - self.last_blink
        if t < self.blink_close_ms:              # zamknięte
            return 0.25
        if t < self.blink_close_ms + self.blink_after_ms:  # after-blink
            return 0.6
        return 1.0

# --- wybór backendu -----------------------------------------------------------
class _Dummy(BaseRenderer):
    def render(self, model: FaceModel): pass
    def close(self): pass

def pick_renderer(cfg: FaceConfig) -> BaseRenderer:
    if cfg.backend_env in ("lcd", "led"):
        try:
            print("[face] backend=LCD", flush=True)
            return LCDRenderer(cfg)
        except Exception as e:
            print(f"[face] LCD fail: {e} → TK", flush=True)
            try: return TKRenderer(cfg)
            except Exception: return _Dummy()
    if cfg.backend_env == "tk":
        try: return TKRenderer(cfg)
        except Exception: return _Dummy()
    try:
        print("[face] backend=LCD(auto)", flush=True)
        return LCDRenderer(cfg)
    except Exception:
        print("[face] backend=TK(auto)", flush=True)
        try: return TKRenderer(cfg)
        except Exception: return _Dummy()

# --- app ----------------------------------------------------------------------
def _cleanup(renderer):
    try: renderer.close()
    except Exception: pass
    release_lock()

class FaceApp:
    def __init__(self):
        acquire_lock()
        self.model = FaceModel()
        # zbuduj FaceConfig z ENV
        self.cfg = FaceConfig(
            backend_env=BACKEND_ENV,
            fps=FPS,
            bench=BENCH,
            guide=GUIDE,
            brow_caps=BROW_CAPS,
            brow_style=BROW_STYLE,
            quality=QUALITY,
            brow_taper=BROW_TAPER,
            brow_y_k=BROW_Y_K,
            brow_h_k=BROW_H_K,
            mouth_y_k=MOUTH_Y_K,
            head_ky=HEAD_KY,
            lcd_do_init=LCD_DO_INIT,
            lcd_rotate=LCD_ROTATE,
            lcd_spi_hz=LCD_SPI_HZ,
            lcd_bl_pin=int(os.environ.get("FACE_LCD_BL_PIN", "13")),
            takeover_mode=LCD_TAKEOVER_MODE,
            kill_re=LCD_KILL_RE,
            colors=COLORS,
        )
        self.renderer = pick_renderer(self.cfg)
        self.q = queue.Queue()

        # bus: subs i pub (heartbeat)
        self.sub_state = BusSub("ui.state");           self.sub_asst = BusSub("assistant.speech")
        self.sub_tr    = BusSub("audio.transcript");   self.sub_set  = BusSub("ui.face.set")
        self.sub_cfg   = BusSub("ui.face.config");     self.pub      = BusPub()

        self.bus_th = threading.Thread(target=self._bus_loop, daemon=True); self.bus_th.start()
        try:
            u = platform.uname(); print(f"[face] {u.system} {u.release} {u.machine}", flush=True)
        except Exception: pass
        atexit.register(lambda: _cleanup(self.renderer))
        signal.signal(signal.SIGINT,  lambda *_: sys.exit(0))
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        self._bench_last_cpu = time.process_time()
        self._bench_last_wall = perf_counter()
        self._bench_frames = 0
        self._dyn_fps = float(FPS)
        self._hb_last = 0.0

    # --- BUS ------------------------------------------------------------------
    def _bus_loop(self):
        subs = (
            (self.sub_state, "state"),
            (self.sub_asst,  "assistant"),
            (self.sub_tr,    "transcript"),
            (self.sub_set,   "set"),
            (self.sub_cfg,   "cfg"),
        )
        while True:
            for sub, typ in subs:
                topic, payload = sub.recv(timeout_ms=50)
                if not topic or not payload:
                    continue
                try:
                    if typ=="state":
                        self.q.put({"type":"state","state": str(payload.get("state","idle"))})
                    elif typ=="assistant":
                        self.q.put({"type":"assistant","event": str(payload.get("event","")), "text": str(payload.get("text",""))})
                    elif typ=="transcript":
                        self.q.put({"type":"transcript","text": str(payload.get("text",""))})
                    elif typ=="set":
                        self.q.put({"type":"face_set","payload": payload})
                    elif typ=="cfg":
                        self.q.put({"type":"face_cfg","payload": payload})
                except Exception:
                    continue

    def _apply_face_set(self, payload: dict):
        expr  = str(payload.get("expr","")) or None
        inten = payload.get("intensity", None)
        if inten is not None:
            try: inten = float(inten)
            except Exception: inten = None
        blink = bool(payload.get("blink", False))

        if expr:
            self.model.expr = expr
            # mapowanie expr -> state (kolor tła, tempo itp.)
            if expr in ("wake","record","process","speak","low_battery","idle"):
                self.model.state = expr
            elif expr == "neutral":
                self.model.state = "idle"
            elif expr == "happy":
                self.model.state = "idle"
        if isinstance(inten, float):
            self.model.expr_intensity = max(0.0, min(1.0, inten))
        if blink:
            self.model.trigger_blink()

    def _apply_face_cfg(self, payload: dict):
        cfg = self.cfg
        def _upd_float(key, lo, hi, attr):
            if key in payload:
                try:
                    val = max(lo, min(hi, float(payload.get(key, getattr(cfg, attr)))))
                    setattr(cfg, attr, val)
                    print(f"[face] cfg: {attr.upper()}={getattr(cfg, attr)}", flush=True)
                except Exception:
                    pass

        _upd_float("head_ky",   0.90, 1.20, "head_ky")
        _upd_float("brow_y_k",  0.14, 0.30, "brow_y_k")
        _upd_float("brow_h_k",  0.06, 0.16, "brow_h_k")
        _upd_float("mouth_y_k", 0.18, 0.28, "mouth_y_k")
        _upd_float("brow_taper",0.0,  1.0,  "brow_taper")

        if "guide" in payload:
            try:
                cfg.guide = bool(int(payload.get("guide", int(cfg.guide))))
                print(f"[face] cfg: GUIDE={cfg.guide}", flush=True)
            except Exception: pass

        if "brow_caps" in payload:
            try:
                cfg.brow_caps = bool(int(payload.get("brow_caps", int(cfg.brow_caps))))
                print(f"[face] cfg: BROW_CAPS={cfg.brow_caps}", flush=True)
            except Exception: pass

        if "quality" in payload:
            q = str(payload.get("quality", cfg.quality)).strip().lower()
            if q in ("fast","aa2x"):
                cfg.quality = q; print(f"[face] cfg: QUALITY={cfg.quality}", flush=True)

        if "brow_style" in payload:
            bs = str(payload.get("brow_style", cfg.brow_style)).strip().lower()
            if bs in ("classic","tapered"):
                cfg.brow_style = bs; print(f"[face] cfg: BROW_STYLE={cfg.brow_style}", flush=True)

        if "lcd_spi_hz" in payload:
            try:
                hz = int(payload.get("lcd_spi_hz"))
                cfg.lcd_spi_hz = hz
                if hasattr(self.renderer, "set_spi_speed"):
                    ok = self.renderer.set_spi_speed(hz)
                    print(f"[face] cfg: set SPI {hz} → {'OK' if ok else 'NOOP'}", flush=True)
            except Exception as e:
                print(f"[face] cfg: spi err: {e}", flush=True)

    def _drain(self):
        try:
            while True:
                ev = self.q.get_nowait()
                t = ev.get("type")
                if t=="state":
                    self.model.state = ev.get("state","idle")
                elif t=="assistant":
                    evt = ev.get("event",""); txt = ev.get("text","")
                    if evt=="start":
                        self.model.assist_speaking=True; self.model.assistant_text=txt; self.model.state="speak"
                    elif evt=="end":
                        self.model.assist_speaking=False; self.model.state="idle"
                elif t=="transcript":
                    self.model.user_text = ev.get("text","")
                elif t=="face_set":
                    self._apply_face_set(ev.get("payload", {}))
                elif t=="face_cfg":
                    self._apply_face_cfg(ev.get("payload", {}))
        except queue.Empty:
            pass

    def _maybe_print_bench(self):
        if not BENCH: return
        self._bench_frames += 1
        now_wall = perf_counter()
        if now_wall - self._bench_last_wall >= 1.0:
            cpu_now = time.process_time()
            wall_dt = now_wall - self._bench_last_wall
            cpu_dt  = cpu_now - self._bench_last_cpu
            fps = self._bench_frames / max(1e-6, wall_dt)
            cpu_pct = 100.0 * cpu_dt / max(1e-6, wall_dt)
            draw_ms = float(getattr(self.renderer, "_bench_draw_ms", 0.0))
            push_ms = float(getattr(self.renderer, "_bench_push_ms", 0.0))
            extra = (f" afps~{self._dyn_fps:.1f}" if AUTO_FPS else "")
            print(f"[bench] fps={fps:.1f}  cpu~{cpu_pct:.0f}%  draw={draw_ms:.1f}ms  push={push_ms:.1f}ms{extra}", flush=True)
            self._bench_last_wall = now_wall; self._bench_last_cpu = cpu_now; self._bench_frames = 0

    def _maybe_heartbeat(self):
        now = time.time()
        if now - self._hb_last < 5.0:  # co 5s
            return
        self._hb_last = now
        try:
            draw_ms = float(getattr(self.renderer, "_bench_draw_ms", 0.0))
            push_ms = float(getattr(self.renderer, "_bench_push_ms", 0.0))
            payload = {
                "app": "ui.face",
                "pid": os.getpid(),
                "ver": APP_VER,
                "fps": self._dyn_fps if AUTO_FPS else float(FPS),
                "draw_ms": draw_ms,
                "push_ms": push_ms,
                "state": self.model.state,
                "expr": self.model.expr or "",
                "intensity": float(self.model.expr_intensity),
                "backend": (
                    "lcd" if isinstance(self.renderer, LCDRenderer)
                    else ("tk" if isinstance(self.renderer, TKRenderer) else "dummy")
                ),
                "rotate": int(LCD_ROTATE),
                "size": {"w": getattr(self.renderer, "W", None), "h": getattr(self.renderer, "H", None)},
                "canvas": {"w": getattr(self.renderer, "CW", None), "h": getattr(self.renderer, "CH", None)},
                "cfg": {
                    "head_ky": float(self.cfg.head_ky),
                    "brow_caps": int(self.cfg.brow_caps),
                    "brow_style": str(self.cfg.brow_style),
                    "brow_taper": float(self.cfg.brow_taper),
                    "quality": str(self.cfg.quality),
                },
            }
            self.pub.send("system.heartbeat", payload)
        except Exception:
            pass

    def run(self):
        dt = 1.0 / max(1, FPS)
        try:
            while True:
                t0 = perf_counter()
                self._drain()
                self.model.tick(dt)
                self.renderer.render(self.model)
                self._dyn_fps = 1.0 / max(1e-6, perf_counter()-t0)
                self._maybe_print_bench()
                self._maybe_heartbeat()
                sl = dt - (perf_counter() - t0)
                if sl > 0: time.sleep(sl)
        except SystemExit:
            pass
        finally:
            _cleanup(self.renderer)

if __name__ == "__main__" or __name__ == "apps.ui.face":
    FaceApp().run()

